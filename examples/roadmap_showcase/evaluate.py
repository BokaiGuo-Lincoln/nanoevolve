from pathlib import Path

from nanoevolve import Evaluation


def _constants(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        values[name.strip()] = int(raw_value.strip())
    return values


def evaluate(workspace_path: str) -> Evaluation:
    root = Path(workspace_path)
    values = _constants(root / "main.py") | _constants(root / "pkg" / "helper.py")
    score = (
        values["BASE"]
        + values["BONUS"] * 10
        + values["SCALE"] * 5
        + values["OFFSET"] * 3
        + values["LIMIT"] * 2
    )
    size = sum(path.stat().st_size for path in root.rglob("*.py"))
    print(f"evaluated score={score} size={size}")
    return Evaluation(
        score=score,
        feedback="Combined constants from the workspace.",
        metrics={"size": size, "kind": score},
    )
