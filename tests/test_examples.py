import os
import subprocess
import sys
import unittest
from pathlib import Path

from nanoevolve.archive import Archive


ROOT = Path(__file__).resolve().parents[1]


class ExampleIntegrationTests(unittest.TestCase):
    def test_circle_packing_benchmark_improves_the_seed(self):
        completed = subprocess.run(
            [sys.executable, "examples/circle_packing/demo.py"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT)
                + os.pathsep
                + os.environ.get("PYTHONPATH", ""),
            },
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "NanoEvolve circle-packing benchmark completed.", completed.stdout
        )
        project_line = next(
            line for line in completed.stdout.splitlines() if line.startswith("Project: ")
        )
        project = Path(project_line.removeprefix("Project: "))
        archive = Archive.open(project / ".nanoevolve")
        scores = [
            record.evaluation.score
            for record in archive.successful_records()
            if record.evaluation is not None
        ]
        self.assertEqual(len(archive.records), 4)
        self.assertEqual(len(scores), 4)
        self.assertAlmostEqual(scores[0], 0.4)
        self.assertTrue(
            all(left < right for left, right in zip(scores, scores[1:]))
        )
        self.assertAlmostEqual(max(scores), 0.5176380902, places=8)

    def test_advanced_showcase_runs_combined_features_without_network(self):
        cache_dir = ROOT / "examples" / "roadmap_showcase" / "seed" / "__pycache__"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / "test-cache.pyc"
        cache_file.write_bytes(b"not UTF-8")
        try:
            completed = subprocess.run(
                [sys.executable, "examples/roadmap_showcase/demo.py"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PYTHONPATH": str(ROOT)
                    + os.pathsep
                    + os.environ.get("PYTHONPATH", ""),
                },
            )
        finally:
            cache_file.unlink(missing_ok=True)

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("NanoEvolve roadmap showcase completed.", completed.stdout)
        project_line = next(
            line for line in completed.stdout.splitlines() if line.startswith("Project: ")
        )
        project = Path(project_line.removeprefix("Project: "))
        archive = Archive.open(project / ".nanoevolve")
        self.assertEqual(archive.metadata["archive_backend"], "sqlite")
        self.assertEqual(archive.metadata["workers"], 2)
        self.assertEqual(len(archive.records), 5)
        self.assertEqual({record.island for record in archive.records}, {0, 1})
        self.assertTrue(
            all(record.feature_coordinates for record in archive.successful_records())
        )
        self.assertTrue(
            any("workspace/pkg/helper.py" in record.artifacts for record in archive.records)
        )
        prompts = [
            archive.read_artifact(record, "prompt")
            for record in archive.records
            if "prompt" in record.artifacts
        ]
        self.assertTrue(any("Inspiration candidates" in prompt for prompt in prompts))
        self.assertTrue(all("Artifact feedback" in prompt for prompt in prompts))


if __name__ == "__main__":
    unittest.main()
