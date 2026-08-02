from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Callable

from . import __version__
from .archive import Archive, ArchiveError, ArchiveExistsError
from .engine import EvolutionError, evolve
from .mutation import OpenAICompatibleModel
from .types import EvolutionEvent, Record


def _project_files(project: Path) -> tuple[Path, Path, Path, Path]:
    project = project.resolve()
    task_path = project / "TASK.md"
    seed_file = project / "seed.py"
    seed_directory = project / "seed"
    seed_path = seed_file if seed_file.is_file() else seed_directory
    evaluator_path = project / "evaluate.py"
    for path in (task_path, evaluator_path):
        if not path.is_file():
            raise EvolutionError(f"required project file is missing: {path.name}")
    if not seed_path.exists():
        raise EvolutionError("required project seed is missing: seed.py or seed/")
    return task_path, seed_path, evaluator_path, project / ".nanoevolve"


def _load_evaluator(path: Path) -> Callable[[str], object]:
    module_name = f"nanoevolve_project_evaluator_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise EvolutionError(f"cannot import evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluate = getattr(module, "evaluate", None)
    if not callable(evaluate):
        raise EvolutionError("evaluate.py must define a callable evaluate(source_path)")
    return evaluate


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=os.getenv("NANOEVOLVE_MODEL"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("NANOEVOLVE_BASE_URL", "https://api.openai.com/v1"),
    )
    parser.add_argument("--api-key", default=os.getenv("NANOEVOLVE_API_KEY"))
    parser.add_argument("--timeout", type=float, default=30.0)


def _add_evolution_arguments(parser: argparse.ArgumentParser, *, resume: bool) -> None:
    default = None if resume else argparse.SUPPRESS
    parser.add_argument("--json-events", action="store_true")
    parser.add_argument("--target-score", type=float, default=None)
    parser.add_argument("--patience", type=int, default=None)
    parser.add_argument(
        "--mutation-mode",
        choices=("full", "search_replace", "evolve_blocks"),
        default=None if resume else "full",
    )
    parser.add_argument("--evolve-blocks", action="store_true", default=False)
    parser.add_argument("--inspiration-count", type=int, default=None if resume else 0)
    parser.add_argument("--artifact-feedback", action="append", default=default)
    parser.add_argument("--sandbox-command", default=None)
    parser.add_argument("--workers", type=int, default=None if resume else 1)
    parser.add_argument(
        "--archive-backend",
        choices=("jsonl", "sqlite"),
        default=None if resume else "jsonl",
    )
    parser.add_argument("--objective", action="append", default=default)
    parser.add_argument("--feature", action="append", default=default)
    parser.add_argument("--feature-bin", action="append", default=default)
    parser.add_argument("--islands", type=int, default=None if resume else 1)
    parser.add_argument("--migration-interval", type=int, default=None if resume else 0)


def _feature_bins(values: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for value in values:
        try:
            name, raw_width = value.split("=", 1)
            width = float(raw_width)
        except ValueError as error:
            raise EvolutionError(f"invalid feature bin {value!r}; use NAME=WIDTH") from error
        if not name:
            raise EvolutionError("feature bin name must not be empty")
        result[name] = width
    return result


def _evolution_options(
    arguments: argparse.Namespace, metadata: dict | None = None
) -> dict[str, object]:
    metadata = metadata or {}

    def value(name: str, fallback):
        current = getattr(arguments, name, None)
        return metadata.get(name, fallback) if current is None else current

    mutation_mode = value("mutation_mode", "full")
    if arguments.evolve_blocks:
        mutation_mode = "evolve_blocks"
    raw_sandbox = value("sandbox_command", None)
    if isinstance(raw_sandbox, str):
        sandbox_command = shlex.split(raw_sandbox)
    else:
        sandbox_command = raw_sandbox
    raw_bins = value("feature_bin", None)
    bins = (
        dict(metadata.get("feature_bins", {}))
        if raw_bins is None
        else _feature_bins(raw_bins)
    )
    return {
        "mutation_mode": mutation_mode,
        "inspiration_count": value("inspiration_count", 0),
        "artifact_feedback": value("artifact_feedback", []),
        "sandbox_command": sandbox_command,
        "workers": value("workers", 1),
        "archive_backend": value("archive_backend", "jsonl"),
        "objectives": value("objective", metadata.get("objectives", ["score:max"])),
        "features": value("feature", metadata.get("features", [])),
        "feature_bins": bins,
        "islands": value("islands", 1),
        "migration_interval": value("migration_interval", 0),
        "target_score": value("target_score", None),
        "patience": value("patience", None),
    }


def _model(arguments: argparse.Namespace, fallback_name: str | None = None):
    model_name = arguments.model or fallback_name
    if not model_name:
        raise EvolutionError("model is required via --model or NANOEVOLVE_MODEL")
    if not arguments.api_key:
        raise EvolutionError("API key is required via --api-key or NANOEVOLVE_API_KEY")
    return OpenAICompatibleModel(
        model=model_name,
        base_url=arguments.base_url,
        api_key=arguments.api_key,
    )


def _render_event(event: EvolutionEvent) -> None:
    if event.type == "generation_started":
        print(f"generation {event.generation}: started", file=sys.stderr)
    elif event.type == "record_committed":
        print(
            f"generation {event.generation}: {event.data.get('status')} "
            f"{event.record_id}",
            file=sys.stderr,
        )
    elif event.type == "new_best":
        print(
            f"generation {event.generation}: new best {event.data.get('score')}",
            file=sys.stderr,
        )
    elif event.type == "target_reached":
        print(
            f"generation {event.generation}: target score "
            f"{event.data.get('target_score')} reached with {event.data.get('score')}",
            file=sys.stderr,
        )
    elif event.type == "patience_exhausted":
        print(
            f"generation {event.generation}: patience {event.data.get('patience')} "
            f"exhausted; last improvement at generation "
            f"{event.data.get('last_improvement_generation')}",
            file=sys.stderr,
        )


def _render_json_event(event: EvolutionEvent) -> None:
    print(
        json.dumps(
            {
                "type": event.type,
                "generation": event.generation,
                "record_id": event.record_id,
                "data": dict(event.data),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def _event_renderer(arguments: argparse.Namespace) -> Callable[[EvolutionEvent], None]:
    return _render_json_event if arguments.json_events else _render_event


def _print_best(record: Record, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        return
    print(f"record: {record.id}")
    print(f"best score: {record.evaluation.score}")
    print(f"generation: {record.generation}")
    print(f"parent: {record.parent_id or '-'}")
    print(f"source: {record.source_path or '-'}")


def _lineage(archive: Archive, record: Record) -> list[Record]:
    by_id = {item.id: item for item in archive.records}
    lineage = [record]
    current = record
    while current.parent_id is not None:
        try:
            current = by_id[current.parent_id]
        except KeyError as error:
            raise ArchiveError(
                f"record {record.id} has missing parent {current.parent_id}"
            ) from error
        lineage.append(current)
    lineage.reverse()
    return lineage


def _run(arguments: argparse.Namespace) -> int:
    task_path, seed_path, evaluator_path, workdir = _project_files(arguments.project)
    if workdir.exists():
        raise ArchiveExistsError(f"archive already exists: {workdir}")
    best = evolve(
        seed=seed_path,
        evaluate=_load_evaluator(evaluator_path),
        model=_model(arguments),
        task=task_path,
        iterations=arguments.iterations,
        workdir=workdir,
        random_seed=arguments.random_seed,
        timeout=arguments.timeout,
        on_event=_event_renderer(arguments),
        **_evolution_options(arguments),
    )
    _print_best(best)
    return 0


def _resume(arguments: argparse.Namespace) -> int:
    task_path, seed_path, evaluator_path, workdir = _project_files(arguments.project)
    if not workdir.exists():
        raise EvolutionError(f"archive does not exist: {workdir}")
    archive = Archive.open(workdir)
    iterations = (
        arguments.iterations
        if arguments.iterations is not None
        else int(archive.metadata["iterations_requested"])
    )
    random_seed = (
        arguments.random_seed
        if arguments.random_seed is not None
        else int(archive.metadata["random_seed"])
    )
    best = evolve(
        seed=seed_path,
        evaluate=_load_evaluator(evaluator_path),
        model=_model(arguments, fallback_name=archive.metadata.get("model")),
        task=task_path,
        iterations=iterations,
        workdir=workdir,
        random_seed=random_seed,
        timeout=arguments.timeout,
        on_event=_event_renderer(arguments),
        **_evolution_options(arguments, archive.metadata),
    )
    _print_best(best)
    return 0


def _best(arguments: argparse.Namespace) -> int:
    workdir = arguments.project.resolve() / ".nanoevolve"
    archive = Archive.open(workdir)
    record = archive.best(archive.metadata.get("objectives", ("score:max",)))
    _print_best(record, as_json=arguments.json)
    return 0


def _inspect(arguments: argparse.Namespace) -> int:
    workdir = arguments.project.resolve() / ".nanoevolve"
    archive = Archive.open(workdir)
    try:
        record = next(item for item in archive.records if item.id == arguments.record_id)
    except StopIteration as error:
        raise EvolutionError(f"record not found: {arguments.record_id}") from error
    if arguments.artifact:
        sys.stdout.write(archive.read_artifact(record, arguments.artifact))
        return 0
    lineage = _lineage(archive, record)
    if arguments.json:
        print(
            json.dumps(
                {
                    "record": record.to_dict(),
                    "lineage": [item.to_dict() for item in lineage],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(f"record: {record.id}")
    print(f"status: {record.status}")
    print(f"generation: {record.generation}")
    print(f"parent: {record.parent_id or '-'}")
    print(f"selection: {record.selection_mode or '-'}")
    print(f"generation seed: {record.generation_seed}")
    if record.evaluation is not None:
        print(f"score: {record.evaluation.score}")
        print(f"feedback: {record.evaluation.feedback}")
        print(f"metrics: {json.dumps(dict(record.evaluation.metrics), sort_keys=True)}")
    if record.error:
        print(f"error: {record.error}")
    print("lineage: " + " -> ".join(item.id for item in lineage))
    print("artifacts:")
    for name, path in sorted(record.artifacts.items()):
        print(f"  {name}: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanoevolve",
        description="The smallest useful evolutionary programming loop.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="start a new evolution run")
    run_parser.add_argument("project", type=Path)
    run_parser.add_argument("--iterations", type=int, default=100)
    run_parser.add_argument("--random-seed", type=int, default=42)
    _add_evolution_arguments(run_parser, resume=False)
    _add_model_arguments(run_parser)
    run_parser.set_defaults(handler=_run)

    resume_parser = subparsers.add_parser("resume", help="resume to a total generation")
    resume_parser.add_argument("project", type=Path)
    resume_parser.add_argument("--iterations", type=int)
    resume_parser.add_argument("--random-seed", type=int)
    _add_evolution_arguments(resume_parser, resume=True)
    _add_model_arguments(resume_parser)
    resume_parser.set_defaults(handler=_resume)

    best_parser = subparsers.add_parser("best", help="show the best candidate")
    best_parser.add_argument("project", type=Path)
    best_parser.add_argument("--json", action="store_true")
    best_parser.set_defaults(handler=_best)

    inspect_parser = subparsers.add_parser("inspect", help="inspect one record")
    inspect_parser.add_argument("project", type=Path)
    inspect_parser.add_argument("record_id")
    inspect_output = inspect_parser.add_mutually_exclusive_group()
    inspect_output.add_argument("--json", action="store_true")
    inspect_output.add_argument("--artifact")
    inspect_parser.set_defaults(handler=_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
        return arguments.handler(arguments)
    except (ArchiveError, EvolutionError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
