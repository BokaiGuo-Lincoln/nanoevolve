from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

from nanoevolve import evolve
from nanoevolve.archive import Archive


class ShowcaseModel:
    model = "deterministic-roadmap-showcase"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.responses = iter(
            [
                self.patch("main.py", "BONUS = 0\n", "BONUS = 1\n"),
                self.patch("pkg/helper.py", "SCALE = 1\n", "SCALE = 4\n"),
                self.patch("pkg/helper.py", "OFFSET = 0\n", "OFFSET = 6\n"),
                self.patch("pkg/helper.py", "LIMIT = 1\n", "LIMIT = 10\n"),
            ]
        )

    @staticmethod
    def patch(path: str, search: str, replacement: str) -> str:
        return (
            "<<<<<<< SEARCH\n"
            f"path: {path}\n"
            f"{search}"
            "=======\n"
            f"{replacement}"
            ">>>>>>> REPLACE\n"
        )

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


def load_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("roadmap_showcase_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


def main() -> None:
    source_dir = Path(__file__).resolve().parent
    project = Path(tempfile.mkdtemp(prefix="nanoevolve-roadmap-"))
    shutil.copy2(source_dir / "TASK.md", project / "TASK.md")
    shutil.copy2(source_dir / "evaluate.py", project / "evaluate.py")
    shutil.copytree(
        source_dir / "seed",
        project / "seed",
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]"),
    )
    model = ShowcaseModel()

    best = evolve(
        seed=project / "seed",
        evaluate=load_evaluator(project / "evaluate.py"),
        model=model,
        task=project / "TASK.md",
        iterations=4,
        workdir=project / ".nanoevolve",
        random_seed=42,
        mutation_mode="search_replace",
        inspiration_count=2,
        artifact_feedback=("stdout",),
        workers=2,
        archive_backend="sqlite",
        objectives=("score:max", "size:min"),
        features=("kind",),
        feature_bins={"kind": 10},
        islands=2,
        migration_interval=2,
    )

    archive = Archive.open(project / ".nanoevolve")
    prompts = [
        archive.read_artifact(record, "prompt")
        for record in archive.records
        if "prompt" in record.artifacts
    ]
    if not any("Inspiration candidates" in prompt for prompt in prompts):
        raise RuntimeError("showcase did not expose inspiration context")
    if not all("Artifact feedback" in prompt for prompt in prompts):
        raise RuntimeError("showcase did not expose artifact feedback")

    print("NanoEvolve roadmap showcase completed.")
    print(f"Project: {project}")
    print(f"Best score: {best.evaluation.score}")
    print(f"Records: {len(archive.records)}")
    print(f"Backend: {archive.metadata['archive_backend']}")
    print(f"Best record: {best.id}")


if __name__ == "__main__":
    main()
