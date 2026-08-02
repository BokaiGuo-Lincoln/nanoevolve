from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

from nanoevolve import evolve
from nanoevolve.archive import Archive


def candidate(points: list[tuple[str, str]]) -> str:
    rows = "\n".join(f"        ({x}, {y})," for x, y in points)
    return f"```python\ndef solve():\n    return [\n{rows}\n    ]\n```"


class CirclePackingModel:
    model = "deterministic-circle-packing"

    def __init__(self) -> None:
        corners = [("0.0", "0.0"), ("1.0", "0.0"), ("0.0", "1.0"), ("1.0", "1.0")]
        self.responses = iter(
            [
                candidate(
                    corners
                    + [
                        ("0.5", "0.0"),
                        ("0.5", "1.0"),
                        ("0.0", "0.5"),
                        ("1.0", "0.5"),
                    ]
                ),
                candidate(
                    corners
                    + [
                        ("0.5", "0.14"),
                        ("0.5", "0.86"),
                        ("0.14", "0.5"),
                        ("0.86", "0.5"),
                    ]
                ),
                candidate(
                    corners
                    + [
                        ("0.5", "1.0 - 3.0**0.5 / 2.0"),
                        ("0.5", "3.0**0.5 / 2.0"),
                        ("1.0 - 3.0**0.5 / 2.0", "0.5"),
                        ("3.0**0.5 / 2.0", "0.5"),
                    ]
                ),
            ]
        )

    def generate(self, prompt: str) -> str:
        return next(self.responses)


def load_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("circle_packing_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


def main() -> None:
    source_dir = Path(__file__).resolve().parent
    project = Path(tempfile.mkdtemp(prefix="nanoevolve-circle-packing-"))
    for filename in ("TASK.md", "seed.py", "evaluate.py"):
        shutil.copy2(source_dir / filename, project / filename)

    best = evolve(
        seed=project / "seed.py",
        evaluate=load_evaluator(project / "evaluate.py"),
        model=CirclePackingModel(),
        task=project / "TASK.md",
        iterations=3,
        workdir=project / ".nanoevolve",
        random_seed=42,
    )
    archive = Archive.open(project / ".nanoevolve")
    seed = archive.records[0]
    seed_score = seed.evaluation.score if seed.evaluation is not None else 0.0

    print("NanoEvolve circle-packing benchmark completed.")
    print(f"Project: {project}")
    print(f"Seed score: {seed_score:.10f}")
    print(f"Best score: {best.evaluation.score:.10f}")
    print(f"Improvement: {best.evaluation.score - seed_score:.10f}")
    print(f"Records: {len(archive.records)}")
    print(f"Inspect: nanoevolve inspect {project} {best.id}")


if __name__ == "__main__":
    main()
