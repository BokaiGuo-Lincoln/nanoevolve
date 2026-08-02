from __future__ import annotations

import argparse
import importlib.util
import json
import os
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
    seed_path = project / "seed.py"
    evaluator_path = project / "evaluate.py"
    for path in (task_path, seed_path, evaluator_path):
        if not path.is_file():
            raise EvolutionError(f"required project file is missing: {path.name}")
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
        on_event=_render_event,
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
        on_event=_render_event,
    )
    _print_best(best)
    return 0


def _best(arguments: argparse.Namespace) -> int:
    workdir = arguments.project.resolve() / ".nanoevolve"
    record = Archive.open(workdir).best()
    _print_best(record, as_json=arguments.json)
    return 0


def _inspect(arguments: argparse.Namespace) -> int:
    workdir = arguments.project.resolve() / ".nanoevolve"
    archive = Archive.open(workdir)
    try:
        record = next(item for item in archive.records if item.id == arguments.record_id)
    except StopIteration as error:
        raise EvolutionError(f"record not found: {arguments.record_id}") from error
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
    _add_model_arguments(run_parser)
    run_parser.set_defaults(handler=_run)

    resume_parser = subparsers.add_parser("resume", help="resume to a total generation")
    resume_parser.add_argument("project", type=Path)
    resume_parser.add_argument("--iterations", type=int)
    resume_parser.add_argument("--random-seed", type=int)
    _add_model_arguments(resume_parser)
    resume_parser.set_defaults(handler=_resume)

    best_parser = subparsers.add_parser("best", help="show the best candidate")
    best_parser.add_argument("project", type=Path)
    best_parser.add_argument("--json", action="store_true")
    best_parser.set_defaults(handler=_best)

    inspect_parser = subparsers.add_parser("inspect", help="inspect one record")
    inspect_parser.add_argument("project", type=Path)
    inspect_parser.add_argument("record_id")
    inspect_parser.add_argument("--json", action="store_true")
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
