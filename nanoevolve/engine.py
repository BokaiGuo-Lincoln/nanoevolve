from __future__ import annotations

import hashlib
import json
import math
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .archive import Archive, ArchiveError
from .mutation import (
    InvalidModelResponse,
    Model,
    apply_evolve_blocks,
    apply_search_replace,
    build_prompt,
    extract_workspace,
)
from .runner import RunnerResult, SubprocessRunner, resolve_evaluator
from .types import Evaluation, EvolutionEvent, Record, RecordStatus


class EvolutionError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_required(path: str | Path, label: str) -> tuple[Path, str, str]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise EvolutionError(f"{label} file is missing: {resolved}")
    raw = resolved.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvolutionError(f"{label} file must be UTF-8: {resolved}") from error
    return resolved, text, _sha256_bytes(raw)


def read_workspace(path: str | Path) -> dict[str, str]:
    original = Path(path).expanduser()
    if original.is_symlink():
        raise EvolutionError(f"seed path must not be a symlink: {original}")
    resolved = original.resolve()
    if resolved.is_file():
        paths = [(resolved.name, resolved)]
    elif resolved.is_dir():
        entries = list(sorted(resolved.rglob("*")))
        symlinks = [item for item in entries if item.is_symlink()]
        if symlinks:
            raise EvolutionError(f"seed workspace contains a symlink: {symlinks[0]}")
        paths = [
            (item.relative_to(resolved).as_posix(), item)
            for item in entries
            if item.is_file()
        ]
    else:
        raise EvolutionError(f"seed path is missing: {resolved}")
    if not paths:
        raise EvolutionError(f"seed workspace is empty: {resolved}")
    workspace: dict[str, str] = {}
    for relative_path, item in paths:
        try:
            workspace[relative_path] = item.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise EvolutionError(f"workspace file must be UTF-8: {item}") from error
    return workspace


def _workspace_hash(path: Path, workspace: Mapping[str, str]) -> str:
    if path.is_file():
        return _sha256_bytes(path.read_bytes())
    payload = json.dumps(dict(sorted(workspace.items())), separators=(",", ":"))
    return _sha256_bytes(payload.encode())


def _workspace_text(workspace: Mapping[str, str]) -> str:
    if len(workspace) == 1:
        return next(iter(workspace.values()))
    return "\n".join(
        f"### FILE: {path}\n```python\n{source.rstrip()}\n```"
        for path, source in sorted(workspace.items())
    ) + "\n"


def _runner_input(workspace: Mapping[str, str], multi_file: bool) -> str | Mapping[str, str]:
    return workspace if multi_file else next(iter(workspace.values()))


def _workspace_artifacts(
    workspace: Mapping[str, str], multi_file: bool
) -> dict[str, str]:
    if not multi_file:
        return {"source.py": next(iter(workspace.values()))}
    return {f"workspace/{path}": source for path, source in workspace.items()}


def _read_record_workspace(archive: Archive, record: Record) -> dict[str, str]:
    if "source" in record.artifacts:
        return {
            str(archive.metadata.get("seed_name", "seed.py")): archive.read_artifact(
                record, "source"
            )
        }
    workspace: dict[str, str] = {}
    for name in record.artifacts:
        if name.startswith("workspace/"):
            workspace[name.removeprefix("workspace/")] = archive.read_artifact(
                record, name
            )
    if not workspace:
        raise ArchiveError(f"record {record.id} has no workspace artifacts")
    return workspace


def _model_name(model: Model) -> str:
    value = getattr(model, "model", None)
    return str(value) if value else type(model).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_id(
    run_id: str,
    generation: int,
    parent_id: str | None,
    status: RecordStatus,
    response: str | None,
    workspace: Mapping[str, str] | None,
    error: str | None,
) -> str:
    payload = json.dumps(
        {
            "run_id": run_id,
            "generation": generation,
            "parent_id": parent_id,
            "status": status,
            "response_hash": _sha256_bytes(response.encode()) if response else None,
            "workspace_hash": (
                _sha256_bytes(
                    json.dumps(dict(sorted(workspace.items())), separators=(",", ":")).encode()
                )
                if workspace
                else None
            ),
            "error": error,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _evaluation_artifact(evaluation: Evaluation | None) -> str | None:
    if evaluation is None:
        return None
    return json.dumps(evaluation.to_dict(), indent=2, sort_keys=True) + "\n"


def _emit(
    callback: Callable[[EvolutionEvent], None] | None,
    event_type: str,
    generation: int,
    record_id: str | None = None,
    **data: object,
) -> None:
    if callback is not None:
        callback(EvolutionEvent(event_type, generation, record_id, data))


def _coordinates(
    evaluation: Evaluation | None,
    features: Sequence[str],
    feature_bins: Mapping[str, float],
) -> tuple[int, ...]:
    if evaluation is None or not features:
        return ()
    try:
        return tuple(
            math.floor(evaluation.metrics[name] / feature_bins[name]) for name in features
        )
    except KeyError:
        return ()


def _commit_runner_result(
    archive: Archive,
    *,
    generation: int,
    parent_id: str | None,
    selection_mode: str,
    generation_seed: int,
    workspace: Mapping[str, str],
    multi_file: bool,
    prompt: str | None,
    response: str | None,
    runner_result: RunnerResult,
    island: int,
    features: Sequence[str],
    feature_bins: Mapping[str, float],
) -> Record:
    record = Record(
        id=_record_id(
            archive.metadata["run_id"],
            generation,
            parent_id,
            runner_result.status,
            response,
            workspace,
            runner_result.error,
        ),
        parent_id=parent_id,
        generation=generation,
        status=runner_result.status,
        source_path=None,
        evaluation=runner_result.evaluation,
        error=runner_result.error,
        selection_mode=selection_mode,
        generation_seed=generation_seed,
        created_at=_now(),
        island=island,
        feature_coordinates=_coordinates(
            runner_result.evaluation, features, feature_bins
        ),
    )
    artifacts = _workspace_artifacts(workspace, multi_file)
    if prompt is not None:
        artifacts["prompt.txt"] = prompt
    if response is not None:
        artifacts["response.txt"] = response
    evaluation_json = _evaluation_artifact(runner_result.evaluation)
    if evaluation_json is not None:
        artifacts["evaluation.json"] = evaluation_json
    artifacts["stdout.txt"] = runner_result.stdout
    artifacts["stderr.txt"] = runner_result.stderr
    return archive.commit(record, artifacts)


def _failed_record(
    archive: Archive,
    generation: int,
    parent: Record,
    status: RecordStatus,
    error: str,
    selection_mode: str,
    generation_seed: int,
    response: str | None,
    prompt: str,
    island: int,
) -> Record:
    record = Record(
        id=_record_id(
            archive.metadata["run_id"],
            generation,
            parent.id,
            status,
            response,
            None,
            error,
        ),
        parent_id=parent.id,
        generation=generation,
        status=status,
        source_path=None,
        evaluation=None,
        error=error,
        selection_mode=selection_mode,
        generation_seed=generation_seed,
        created_at=_now(),
        island=island,
    )
    artifacts = {"prompt.txt": prompt, "stderr.txt": error + "\n"}
    if response is not None:
        artifacts["response.txt"] = response
    return archive.commit(record, artifacts)


def _normalized_options(
    *,
    mutation_mode: str,
    inspiration_count: int,
    artifact_feedback: Sequence[str],
    sandbox_command: Sequence[str] | None,
    workers: int,
    archive_backend: str,
    objectives: Sequence[str],
    features: Sequence[str],
    feature_bins: Mapping[str, float],
    islands: int,
    migration_interval: int,
) -> dict[str, object]:
    if mutation_mode not in {"full", "search_replace", "evolve_blocks"}:
        raise ValueError(f"unknown mutation mode: {mutation_mode}")
    if inspiration_count < 0:
        raise ValueError("inspiration_count must be non-negative")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if archive_backend not in {"jsonl", "sqlite"}:
        raise ValueError("archive_backend must be jsonl or sqlite")
    if islands <= 0:
        raise ValueError("islands must be positive")
    if migration_interval < 0:
        raise ValueError("migration_interval must be non-negative")
    if any(name not in feature_bins for name in features):
        raise ValueError("every feature requires a bin width")
    if any(feature_bins[name] <= 0 for name in features):
        raise ValueError("feature bin widths must be positive")
    if sandbox_command and any(
        marker in token.upper()
        for token in sandbox_command
        for marker in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN", "SECRET", "PASSWORD")
    ):
        raise ValueError("sandbox_command must not contain secrets; use its environment")
    return {
        "mutation_mode": mutation_mode,
        "inspiration_count": inspiration_count,
        "artifact_feedback": list(artifact_feedback),
        "sandbox_command": list(sandbox_command) if sandbox_command else None,
        "workers": workers,
        "archive_backend": archive_backend,
        "objectives": list(objectives),
        "features": list(features),
        "feature_bins": dict(feature_bins),
        "islands": islands,
        "migration_interval": migration_interval,
    }


def _validate_resume(archive: Archive, expected: Mapping[str, object]) -> None:
    legacy_defaults = {
        "mutation_mode": "full",
        "inspiration_count": 0,
        "artifact_feedback": [],
        "sandbox_command": None,
        "workers": 1,
        "archive_backend": "jsonl",
        "objectives": ["score:max"],
        "features": [],
        "feature_bins": {},
        "islands": 1,
        "migration_interval": 0,
    }
    mismatches = [
        name
        for name, value in expected.items()
        if archive.metadata.get(name, legacy_defaults.get(name)) != value
    ]
    if mismatches:
        raise EvolutionError(
            "run inputs changed and cannot be resumed: " + ", ".join(mismatches)
        )


def _apply_response(
    parent: Mapping[str, str],
    response: str,
    mutation_mode: str,
    default_path: str,
    multi_file: bool,
) -> dict[str, str]:
    if mutation_mode == "full":
        candidate = extract_workspace(response, default_path)
    elif mutation_mode == "search_replace":
        candidate = apply_search_replace(parent, response)
    else:
        candidate = apply_evolve_blocks(parent, response)
    if not multi_file and set(candidate) != {default_path}:
        raise InvalidModelResponse(
            "single-file runs must return exactly the original seed path"
        )
    return candidate


def _inspirations(
    archive: Archive, parent: Record, count: int
) -> list[tuple[str, str, Evaluation]]:
    records = sorted(
        (record for record in archive.successful_records() if record.id != parent.id),
        key=lambda record: (-record.evaluation.score, record.id),
    )[:count]
    return [
        (record.id, _workspace_text(_read_record_workspace(archive, record)), record.evaluation)
        for record in records
    ]


def evolve(
    seed: str | Path,
    evaluate: Callable[[str], object],
    model: Model,
    task: str | Path,
    iterations: int = 100,
    workdir: str | Path = ".nanoevolve",
    random_seed: int = 42,
    timeout: float = 30,
    on_event: Callable[[EvolutionEvent], None] | None = None,
    *,
    mutation_mode: str = "full",
    evolve_blocks: bool = False,
    inspiration_count: int = 0,
    artifact_feedback: Sequence[str] = (),
    sandbox_command: Sequence[str] | None = None,
    workers: int = 1,
    archive_backend: str = "jsonl",
    objectives: Sequence[str] = ("score:max",),
    features: Sequence[str] = (),
    feature_bins: Mapping[str, float] | None = None,
    islands: int = 1,
    migration_interval: int = 0,
) -> Record:
    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    if evolve_blocks:
        if mutation_mode != "full":
            raise ValueError("evolve_blocks conflicts with mutation_mode")
        mutation_mode = "evolve_blocks"
    bins = dict(feature_bins or {})
    options = _normalized_options(
        mutation_mode=mutation_mode,
        inspiration_count=inspiration_count,
        artifact_feedback=artifact_feedback,
        sandbox_command=sandbox_command,
        workers=workers,
        archive_backend=archive_backend,
        objectives=objectives,
        features=features,
        feature_bins=bins,
        islands=islands,
        migration_interval=migration_interval,
    )
    seed_path = Path(seed).resolve()
    seed_workspace = read_workspace(seed_path)
    multi_file = seed_path.is_dir()
    seed_hash = _workspace_hash(seed_path, seed_workspace)
    task_path, task_text, task_hash = _read_required(task, "task")
    evaluator = resolve_evaluator(evaluate)
    evaluator_hash = _sha256_bytes(evaluator.path.read_bytes())
    model_name = _model_name(model)
    workdir_path = Path(workdir).resolve()
    runner = SubprocessRunner(
        timeout=timeout,
        sandbox_command=tuple(sandbox_command) if sandbox_command else None,
    )
    resume_inputs = {
        "task_hash": task_hash,
        "seed_hash": seed_hash,
        "evaluator_hash": evaluator_hash,
        "model": model_name,
        "random_seed": random_seed,
        **options,
    }

    if workdir_path.exists():
        archive = Archive.open(workdir_path)
        _validate_resume(archive, resume_inputs)
        multi_file = bool(archive.metadata.get("multi_file", False))
    else:
        archive = Archive.create(
            workdir_path,
            {
                "format_version": 2,
                "run_id": uuid.uuid4().hex,
                "task_path": str(task_path),
                "task_hash": task_hash,
                "seed_path": str(seed_path),
                "seed_name": next(iter(seed_workspace)),
                "seed_hash": seed_hash,
                "multi_file": multi_file,
                "evaluator_path": str(evaluator.path),
                "evaluator_name": evaluator.function_name,
                "evaluator_hash": evaluator_hash,
                "model": model_name,
                "iterations_requested": iterations,
                "random_seed": random_seed,
                "created_at": _now(),
                **options,
            },
        )
        _emit(on_event, "generation_started", 0)
        seed_result = runner.run(_runner_input(seed_workspace, multi_file), evaluate)
        seed_record = _commit_runner_result(
            archive,
            generation=0,
            parent_id=None,
            selection_mode="seed",
            generation_seed=random_seed,
            workspace=seed_workspace,
            multi_file=multi_file,
            prompt=None,
            response=None,
            runner_result=seed_result,
            island=0,
            features=features,
            feature_bins=bins,
        )
        _emit(on_event, "record_committed", 0, seed_record.id, status=seed_record.status)
        if seed_record.status != "success":
            raise EvolutionError(
                f"seed evaluation failed with status {seed_record.status}: {seed_record.error}"
            )
        _emit(on_event, "new_best", 0, seed_record.id, score=seed_record.evaluation.score)

    current = max((record.generation for record in archive.records), default=-1) + 1
    while current <= iterations:
        generations = list(range(max(1, current), min(iterations + 1, current + workers)))
        prepared: dict[int, tuple[Record, str, int, int, str, str | None, dict[str, str] | None]] = {}
        for generation in generations:
            _emit(on_event, "generation_started", generation)
            parent, selection_mode, generation_seed = archive.select_parent(
                run_seed=random_seed,
                generation=generation,
                objectives=objectives,
                features=features,
                feature_bins=bins,
                islands=islands,
                migration_interval=migration_interval,
            )
            island = generation % islands
            _emit(
                on_event,
                "parent_selected",
                generation,
                parent.id,
                selection_mode=selection_mode,
                generation_seed=generation_seed,
                island=island,
            )
            parent_workspace = _read_record_workspace(archive, parent)
            feedback = {
                name: archive.read_artifact(parent, name)[:16384]
                for name in artifact_feedback
                if name in parent.artifacts
            }
            prompt = build_prompt(
                task_text,
                _workspace_text(parent_workspace),
                parent.evaluation,
                mutation_mode=mutation_mode,
                inspirations=_inspirations(archive, parent, inspiration_count),
                artifact_feedback=feedback,
                multi_file=multi_file,
            )
            try:
                response = model.generate(prompt)
            except Exception as error:
                prepared[generation] = (
                    parent,
                    selection_mode,
                    generation_seed,
                    island,
                    prompt,
                    f"{type(error).__name__}: {error}",
                    None,
                )
                continue
            _emit(on_event, "model_completed", generation, parent.id)
            try:
                candidate = _apply_response(
                    parent_workspace,
                    response,
                    mutation_mode,
                    str(archive.metadata.get("seed_name", "seed.py")),
                    multi_file,
                )
            except InvalidModelResponse as error:
                prepared[generation] = (
                    parent,
                    selection_mode,
                    generation_seed,
                    island,
                    prompt,
                    str(error),
                    {"__response__": response},
                )
            else:
                _emit(on_event, "candidate_extracted", generation, parent.id)
                prepared[generation] = (
                    parent,
                    selection_mode,
                    generation_seed,
                    island,
                    prompt,
                    response,
                    candidate,
                )

        futures: dict[int, Future[RunnerResult]] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for generation, item in prepared.items():
                candidate = item[6]
                if candidate is not None and "__response__" not in candidate:
                    futures[generation] = executor.submit(
                        runner.run, _runner_input(candidate, multi_file), evaluate
                    )

            for generation in generations:
                parent, mode, generation_seed, island, prompt, detail, candidate = prepared[generation]
                previous_best = archive.best(objectives).id
                if candidate is None:
                    committed = _failed_record(
                        archive,
                        generation,
                        parent,
                        "model_error",
                        detail or "model error",
                        mode,
                        generation_seed,
                        None,
                        prompt,
                        island,
                    )
                elif "__response__" in candidate:
                    committed = _failed_record(
                        archive,
                        generation,
                        parent,
                        "invalid_response",
                        detail or "invalid response",
                        mode,
                        generation_seed,
                        candidate["__response__"],
                        prompt,
                        island,
                    )
                else:
                    committed = _commit_runner_result(
                        archive,
                        generation=generation,
                        parent_id=parent.id,
                        selection_mode=mode,
                        generation_seed=generation_seed,
                        workspace=candidate,
                        multi_file=multi_file,
                        prompt=prompt,
                        response=detail,
                        runner_result=futures[generation].result(),
                        island=island,
                        features=features,
                        feature_bins=bins,
                    )
                _emit(on_event, "record_committed", generation, committed.id, status=committed.status)
                if committed.status != "success":
                    _emit(
                        on_event,
                        "generation_failed",
                        generation,
                        committed.id,
                        status=committed.status,
                        error=committed.error,
                    )
                elif archive.best(objectives).id != previous_best:
                    _emit(
                        on_event,
                        "new_best",
                        generation,
                        committed.id,
                        score=committed.evaluation.score,
                    )
        current = generations[-1] + 1

    return archive.best(objectives)
