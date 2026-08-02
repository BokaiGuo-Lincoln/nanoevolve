from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .archive import Archive, ArchiveError
from .mutation import InvalidModelResponse, Model, build_prompt, extract_python_source
from .runner import SubprocessRunner, resolve_evaluator
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
    source: str | None,
    error: str | None,
) -> str:
    payload = json.dumps(
        {
            "run_id": run_id,
            "generation": generation,
            "parent_id": parent_id,
            "status": status,
            "response_hash": _sha256_bytes(response.encode()) if response else None,
            "source_hash": _sha256_bytes(source.encode()) if source else None,
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


def _commit_runner_result(
    archive: Archive,
    *,
    generation: int,
    parent_id: str | None,
    selection_mode: str,
    generation_seed: int,
    source: str,
    prompt: str | None,
    response: str | None,
    runner_result,
) -> Record:
    run_id = archive.metadata["run_id"]
    record = Record(
        id=_record_id(
            run_id,
            generation,
            parent_id,
            runner_result.status,
            response,
            source,
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
    )
    artifacts: dict[str, str] = {"source.py": source}
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


def _validate_resume(
    archive: Archive,
    *,
    task_hash: str,
    seed_hash: str,
    evaluator_hash: str,
    model_name: str,
    random_seed: int,
) -> None:
    expected = {
        "task_hash": task_hash,
        "seed_hash": seed_hash,
        "evaluator_hash": evaluator_hash,
        "model": model_name,
        "random_seed": random_seed,
    }
    mismatches = [
        name
        for name, value in expected.items()
        if archive.metadata.get(name) != value
    ]
    if mismatches:
        raise EvolutionError(
            "run inputs changed and cannot be resumed: " + ", ".join(mismatches)
        )


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
) -> Record:
    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    seed_path, seed_source, seed_hash = _read_required(seed, "seed")
    task_path, task_text, task_hash = _read_required(task, "task")
    evaluator = resolve_evaluator(evaluate)
    evaluator_hash = _sha256_bytes(evaluator.path.read_bytes())
    model_name = _model_name(model)
    workdir_path = Path(workdir).resolve()
    runner = SubprocessRunner(timeout=timeout)

    if workdir_path.exists():
        archive = Archive.open(workdir_path)
        _validate_resume(
            archive,
            task_hash=task_hash,
            seed_hash=seed_hash,
            evaluator_hash=evaluator_hash,
            model_name=model_name,
            random_seed=random_seed,
        )
    else:
        archive = Archive.create(
            workdir_path,
            {
                "format_version": 1,
                "run_id": uuid.uuid4().hex,
                "task_path": str(task_path),
                "task_hash": task_hash,
                "seed_path": str(seed_path),
                "seed_hash": seed_hash,
                "evaluator_path": str(evaluator.path),
                "evaluator_name": evaluator.function_name,
                "evaluator_hash": evaluator_hash,
                "model": model_name,
                "iterations_requested": iterations,
                "random_seed": random_seed,
                "created_at": _now(),
            },
        )
        _emit(on_event, "generation_started", 0)
        seed_result = runner.run(seed_source, evaluate)
        seed_record = _commit_runner_result(
            archive,
            generation=0,
            parent_id=None,
            selection_mode="seed",
            generation_seed=random_seed,
            source=seed_source,
            prompt=None,
            response=None,
            runner_result=seed_result,
        )
        _emit(
            on_event,
            "record_committed",
            0,
            seed_record.id,
            status=seed_record.status,
        )
        if seed_record.status != "success":
            raise EvolutionError(
                f"seed evaluation failed with status {seed_record.status}: "
                f"{seed_record.error}"
            )
        _emit(on_event, "new_best", 0, seed_record.id, score=seed_record.evaluation.score)

    current_generation = max((record.generation for record in archive.records), default=-1)
    for generation in range(max(1, current_generation + 1), iterations + 1):
        _emit(on_event, "generation_started", generation)
        parent, selection_mode, generation_seed = archive.select_parent(
            run_seed=random_seed,
            generation=generation,
        )
        _emit(
            on_event,
            "parent_selected",
            generation,
            parent.id,
            selection_mode=selection_mode,
            generation_seed=generation_seed,
        )
        parent_source = archive.read_artifact(parent, "source")
        prompt = build_prompt(task_text, parent_source, parent.evaluation)
        previous_best_score = archive.best().evaluation.score

        try:
            response = model.generate(prompt)
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
            failed = Record(
                id=_record_id(
                    archive.metadata["run_id"],
                    generation,
                    parent.id,
                    "model_error",
                    None,
                    None,
                    error_text,
                ),
                parent_id=parent.id,
                generation=generation,
                status="model_error",
                source_path=None,
                evaluation=None,
                error=error_text,
                selection_mode=selection_mode,
                generation_seed=generation_seed,
                created_at=_now(),
            )
            committed = archive.commit(
                failed,
                {"prompt.txt": prompt, "stderr.txt": error_text + "\n"},
            )
        else:
            _emit(on_event, "model_completed", generation, parent.id)
            try:
                candidate_source = extract_python_source(response)
            except InvalidModelResponse as error:
                error_text = str(error)
                failed = Record(
                    id=_record_id(
                        archive.metadata["run_id"],
                        generation,
                        parent.id,
                        "invalid_response",
                        response,
                        None,
                        error_text,
                    ),
                    parent_id=parent.id,
                    generation=generation,
                    status="invalid_response",
                    source_path=None,
                    evaluation=None,
                    error=error_text,
                    selection_mode=selection_mode,
                    generation_seed=generation_seed,
                    created_at=_now(),
                )
                committed = archive.commit(
                    failed,
                    {
                        "prompt.txt": prompt,
                        "response.txt": response,
                        "stderr.txt": error_text + "\n",
                    },
                )
            else:
                _emit(on_event, "candidate_extracted", generation, parent.id)
                runner_result = runner.run(candidate_source, evaluate)
                committed = _commit_runner_result(
                    archive,
                    generation=generation,
                    parent_id=parent.id,
                    selection_mode=selection_mode,
                    generation_seed=generation_seed,
                    source=candidate_source,
                    prompt=prompt,
                    response=response,
                    runner_result=runner_result,
                )

        _emit(
            on_event,
            "record_committed",
            generation,
            committed.id,
            status=committed.status,
        )
        if committed.status != "success":
            _emit(
                on_event,
                "generation_failed",
                generation,
                committed.id,
                status=committed.status,
                error=committed.error,
            )
        elif committed.evaluation.score > previous_best_score:
            _emit(
                on_event,
                "new_best",
                generation,
                committed.id,
                score=committed.evaluation.score,
            )

    try:
        return archive.best()
    except ArchiveError as error:
        raise EvolutionError(str(error)) from error
