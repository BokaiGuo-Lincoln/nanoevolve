import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.release_check import collect_static_failures


ROOT = Path(__file__).resolve().parents[1]


class ReleaseCheckTests(unittest.TestCase):
    def test_readmes_surface_the_circle_packing_benchmark(self):
        for filename in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("python examples/circle_packing/demo.py", readme)

    def test_readmes_surface_json_event_streams(self):
        for filename in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("--json-events", readme)
            self.assertIn("events.jsonl", readme)

    def test_readmes_surface_direct_artifact_inspection(self):
        for filename in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("--artifact prompt", readme)

    def test_readmes_surface_target_score_stopping(self):
        for filename in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("--target-score", readme)

    def test_readmes_surface_patience_stopping(self):
        for filename in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("--patience", readme)

    def test_readmes_surface_run_summaries(self):
        for filename in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("best --summary", readme)
            self.assertIn("status-v0.7_run_evidence", readme)

    def test_current_repository_passes_static_checks(self):
        self.assertEqual(collect_static_failures(ROOT), [])

    def test_detects_release_facing_todo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in (
                "README.md",
                "README.zh-CN.md",
                "CONTRIBUTING.md",
                "SECURITY.md",
                "CHANGELOG.md",
            ):
                (root / filename).write_text("clean\n")
            (root / "README.md").write_text("TODO: publish\n")

            failures = collect_static_failures(root, metadata_checks=False)

        self.assertTrue(any("README.md" in failure for failure in failures))

    def test_checks_only_command_succeeds(self):
        completed = subprocess.run(
            [sys.executable, "scripts/release_check.py", "--checks-only"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("release checks: OK", completed.stdout)


class WorkflowTests(unittest.TestCase):
    def test_ci_covers_platforms_versions_and_package_build(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

        for required in (
            "ubuntu-latest",
            "windows-latest",
            "macos-latest",
            '"3.11"',
            '"3.12"',
            '"3.13"',
            "python -m unittest discover -s tests -v",
            "python scripts/release_check.py --checks-only",
            "python -m build",
            "python -m nanoevolve --version",
            "python -m nanoevolve run --help",
            "python -m nanoevolve inspect --help",
            ".release-venv/bin/python tests/test_cli.py",
            "examples/hello_evolve/demo.py",
            "examples/circle_packing/demo.py",
            "examples/roadmap_showcase/demo.py",
        ):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
