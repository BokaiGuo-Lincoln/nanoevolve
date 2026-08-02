from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = (
    "README.md",
    "README.zh-CN.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
)
CORE_FILES = (
    "nanoevolve/types.py",
    "nanoevolve/mutation.py",
    "nanoevolve/archive.py",
    "nanoevolve/runner.py",
    "nanoevolve/engine.py",
)
CORE_LINE_BUDGET = 1950
FORBIDDEN_PATTERNS = (
    re.compile(r"\bTODO\b"),
    re.compile(r"\bFIXME\b"),
    re.compile(r"\bTBD\b"),
    re.compile(r"<repository-url>", re.IGNORECASE),
    re.compile(r"github\.com/(?:owner|user|username)/", re.IGNORECASE),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _documentation_failures(root: Path) -> list[str]:
    failures: list[str] = []
    texts: dict[str, str] = {}
    for filename in RELEASE_FILES:
        path = root / filename
        if not path.is_file():
            failures.append(f"missing release file: {filename}")
            continue
        text = _read(path)
        texts[filename] = text
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                failures.append(
                    f"{filename} contains forbidden placeholder pattern: {pattern.pattern}"
                )

    english = texts.get("README.md", "")
    chinese = texts.get("README.zh-CN.md", "")
    english_sections = sum(line.startswith("## ") for line in english.splitlines())
    chinese_sections = sum(line.startswith("## ") for line in chinese.splitlines())
    if english_sections != chinese_sections:
        failures.append(
            "README section counts differ: "
            f"English={english_sections}, Chinese={chinese_sections}"
        )
    for token in (
        "nanoevolve run",
        "nanoevolve resume",
        "nanoevolve best",
        "nanoevolve inspect",
        "python -m nanoevolve --version",
        "records.jsonl",
        "SubprocessRunner",
        "scripts/release_check.py",
    ):
        if token not in english:
            failures.append(f"README.md is missing required concept: {token}")
        if token not in chinese:
            failures.append(f"README.zh-CN.md is missing required concept: {token}")
    return failures


def _metadata_failures(root: Path) -> list[str]:
    failures: list[str] = []
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        return ["missing pyproject.toml"]
    metadata = tomllib.loads(_read(pyproject_path))
    project = metadata.get("project", {})
    if project.get("dependencies") != []:
        failures.append("runtime dependencies must remain empty")
    version = project.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?", version):
        failures.append(f"invalid stable package version: {version!r}")
    for field in ("authors", "maintainers", "license", "urls"):
        if field in project:
            failures.append(f"unknown project identity field must remain absent: {field}")
    package_data = (
        metadata.get("tool", {})
        .get("setuptools", {})
        .get("package-data", {})
        .get("nanoevolve", [])
    )
    if "py.typed" not in package_data:
        failures.append("py.typed is not declared as package data")
    if not (root / "nanoevolve" / "py.typed").is_file():
        failures.append("nanoevolve/py.typed is missing")
    return failures


def _core_budget_failures(root: Path) -> list[str]:
    missing = [filename for filename in CORE_FILES if not (root / filename).is_file()]
    if missing:
        return ["missing core files: " + ", ".join(missing)]
    line_count = sum(len(_read(root / filename).splitlines()) for filename in CORE_FILES)
    if line_count > CORE_LINE_BUDGET:
        return [
            f"core line budget exceeded: {line_count} > {CORE_LINE_BUDGET}"
        ]
    return []


def collect_static_failures(
    root: Path = ROOT,
    *,
    metadata_checks: bool = True,
) -> list[str]:
    failures = _documentation_failures(root)
    if metadata_checks:
        failures.extend(_metadata_failures(root))
        failures.extend(_core_budget_failures(root))
    return failures


def _run(command: list[str], root: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=root, check=True)


def run_release_checks(root: Path = ROOT, *, checks_only: bool = False) -> None:
    if not checks_only:
        _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], root)
        _run([sys.executable, "-m", "compileall", "-q", "nanoevolve", "examples"], root)
    print("+ static release invariants", flush=True)
    failures = collect_static_failures(root)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print("release checks: OK")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the NanoEvolve release surface.")
    parser.add_argument(
        "--checks-only",
        action="store_true",
        help="skip unittest and compileall when they already ran in the caller",
    )
    arguments = parser.parse_args(argv)
    run_release_checks(checks_only=arguments.checks_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
