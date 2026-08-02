from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

from nanoevolve import evolve


class DemoModel:
    model = "deterministic-demo"

    def __init__(self) -> None:
        self.responses = iter(
            [
                "```python\nSCORE = 1\n```",
                "```python\nSCORE = 3\n```",
                "```python\nSCORE = 8\n```",
            ]
        )

    def generate(self, prompt: str) -> str:
        return next(self.responses)


def load_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("hello_evolve_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


def main() -> None:
    source_dir = Path(__file__).resolve().parent
    project = Path(tempfile.mkdtemp(prefix="nanoevolve-hello-"))
    for filename in ("TASK.md", "seed.py", "evaluate.py"):
        shutil.copy2(source_dir / filename, project / filename)

    best = evolve(
        seed=project / "seed.py",
        evaluate=load_evaluator(project / "evaluate.py"),
        model=DemoModel(),
        task=project / "TASK.md",
        iterations=3,
        workdir=project / ".nanoevolve",
        random_seed=42,
    )

    print("NanoEvolve deterministic demo completed.")
    print(f"Project: {project}")
    print(f"Best score: {best.evaluation.score}")
    print(f"Best source: {project / '.nanoevolve' / best.source_path}")
    print(f"Inspect: nanoevolve inspect {project} {best.id}")


if __name__ == "__main__":
    main()
