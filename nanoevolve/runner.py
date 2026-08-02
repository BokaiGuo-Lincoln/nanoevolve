from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .types import Evaluation, RecordStatus


SECRET_NAME_PARTS = (
    "API_KEY",
    "ACCESS_TOKEN",
    "AUTH_TOKEN",
    "SECRET",
    "PASSWORD",
)


class EvaluatorConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluatorSpec:
    path: Path
    function_name: str


@dataclass(frozen=True)
class RunnerResult:
    status: RecordStatus
    evaluation: Evaluation | None
    error: str | None
    stdout: str
    stderr: str


def normalize_evaluation(value: object) -> Evaluation:
    if isinstance(value, Evaluation):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean evaluator results are not scores")
    if isinstance(value, (int, float)):
        return Evaluation(score=value)
    if isinstance(value, Mapping):
        if "score" not in value:
            raise KeyError("evaluator result is missing score")
        return Evaluation(
            score=value["score"],
            feedback=value.get("feedback", ""),
            metrics=value.get("metrics", {}),
        )
    raise TypeError("evaluator must return Evaluation, a score, or a score mapping")


def resolve_evaluator(evaluate: Callable[[str], object]) -> EvaluatorSpec:
    if not inspect.isfunction(evaluate):
        raise EvaluatorConfigurationError("evaluator must be a top-level function")
    if evaluate.__name__ == "<lambda>" or evaluate.__qualname__ != evaluate.__name__:
        raise EvaluatorConfigurationError(
            "lambdas, closures, and nested evaluator functions are not supported"
        )
    source_file = inspect.getsourcefile(evaluate)
    if source_file is None:
        raise EvaluatorConfigurationError("evaluator source file cannot be resolved")
    path = Path(source_file).resolve()
    if not path.is_file():
        raise EvaluatorConfigurationError(f"evaluator source file is missing: {path}")
    return EvaluatorSpec(path=path, function_name=evaluate.__name__)


def sanitized_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environment is None else environment
    sanitized = {
        name: value
        for name, value in source.items()
        if not any(part in name.upper() for part in SECRET_NAME_PARTS)
    }
    package_root = str(Path(__file__).resolve().parent.parent)
    existing_pythonpath = sanitized.get("PYTHONPATH")
    sanitized["PYTHONPATH"] = (
        package_root
        if not existing_pythonpath
        else package_root + os.pathsep + existing_pythonpath
    )
    return sanitized


def _read_limited(path: Path, limit: int) -> str:
    raw = path.read_bytes()
    if len(raw) > limit:
        raw = raw[:limit] + b"\n...[truncated]\n"
    return raw.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class SubprocessRunner:
    timeout: float = 30.0
    output_limit: int = 64 * 1024
    result_limit: int = 1024 * 1024

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.output_limit <= 0:
            raise ValueError("output_limit must be positive")
        if self.result_limit <= 0:
            raise ValueError("result_limit must be positive")

    def run(
        self,
        candidate_source: str,
        evaluate: Callable[[str], object],
    ) -> RunnerResult:
        evaluator = resolve_evaluator(evaluate)
        with tempfile.TemporaryDirectory(prefix="nanoevolve-") as directory:
            workdir = Path(directory)
            candidate_path = workdir / "candidate.py"
            evaluator_path = workdir / "evaluate.py"
            control_path = workdir / "control.json"
            result_path = workdir / "result.json"
            stdout_path = workdir / "stdout.txt"
            stderr_path = workdir / "stderr.txt"

            candidate_path.write_text(candidate_source, encoding="utf-8")
            shutil.copy2(evaluator.path, evaluator_path)
            control_path.write_text(
                json.dumps(
                    {
                        "evaluator_path": str(evaluator_path),
                        "function_name": evaluator.function_name,
                        "candidate_path": str(candidate_path),
                        "result_path": str(result_path),
                    }
                ),
                encoding="utf-8",
            )

            command = [
                sys.executable,
                "-m",
                "nanoevolve.runner",
                "--worker",
                str(control_path),
            ]
            try:
                with stdout_path.open("wb") as stdout_handle, stderr_path.open(
                    "wb"
                ) as stderr_handle:
                    process = subprocess.Popen(
                        command,
                        cwd=workdir,
                        env=sanitized_environment(),
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                    )
                    process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return RunnerResult(
                    status="evaluation_timeout",
                    evaluation=None,
                    error=f"evaluation exceeded {self.timeout} seconds",
                    stdout=_read_limited(stdout_path, self.output_limit),
                    stderr=_read_limited(stderr_path, self.output_limit),
                )

            stdout = _read_limited(stdout_path, self.output_limit)
            stderr = _read_limited(stderr_path, self.output_limit)
            if not result_path.is_file():
                return RunnerResult(
                    status="evaluation_error",
                    evaluation=None,
                    error=f"evaluator worker exited with code {process.returncode}",
                    stdout=stdout,
                    stderr=stderr,
                )
            if result_path.stat().st_size > self.result_limit:
                return RunnerResult(
                    status="invalid_evaluation",
                    evaluation=None,
                    error="structured evaluator result exceeded configured limit",
                    stdout=stdout,
                    stderr=stderr,
                )
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                status = payload["status"]
                evaluation = (
                    Evaluation.from_dict(payload["evaluation"])
                    if payload.get("evaluation") is not None
                    else None
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                return RunnerResult(
                    status="invalid_evaluation",
                    evaluation=None,
                    error=f"invalid evaluator control result: {error}",
                    stdout=stdout,
                    stderr=stderr,
                )
            if status not in {"success", "evaluation_error", "invalid_evaluation"}:
                return RunnerResult(
                    status="invalid_evaluation",
                    evaluation=None,
                    error=f"unknown evaluator worker status: {status}",
                    stdout=stdout,
                    stderr=stderr,
                )
            return RunnerResult(
                status=status,
                evaluation=evaluation,
                error=payload.get("error"),
                stdout=stdout,
                stderr=stderr,
            )


def _load_evaluator(path: Path, function_name: str) -> Callable[[str], object]:
    spec = importlib.util.spec_from_file_location("nanoevolve_user_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluate = getattr(module, function_name)
    if not callable(evaluate):
        raise RuntimeError(f"evaluator attribute is not callable: {function_name}")
    return evaluate


def _worker(control_path: Path) -> int:
    control = json.loads(control_path.read_text(encoding="utf-8"))
    result_path = Path(control["result_path"])
    try:
        evaluate = _load_evaluator(
            Path(control["evaluator_path"]), control["function_name"]
        )
        raw_result = evaluate(control["candidate_path"])
        try:
            evaluation = normalize_evaluation(raw_result)
        except (KeyError, TypeError, ValueError) as error:
            payload: dict[str, Any] = {
                "status": "invalid_evaluation",
                "evaluation": None,
                "error": str(error),
            }
        else:
            payload = {
                "status": "success",
                "evaluation": evaluation.to_dict(),
                "error": None,
            }
    except Exception as error:
        payload = {
            "status": "evaluation_error",
            "evaluation": None,
            "error": f"{type(error).__name__}: {error}\n{traceback.format_exc()}",
        }
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.worker is None:
        parser.error("runner is an internal worker module")
    return _worker(arguments.worker)


if __name__ == "__main__":
    raise SystemExit(main())
