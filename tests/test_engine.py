import tempfile
import time
import unittest
from pathlib import Path

from nanoevolve import EvolutionEvent, evolve
from nanoevolve.archive import Archive
from nanoevolve.engine import EvolutionError, _validate_resume
from tests.fixtures.evaluators import (
    evaluate_score_constant,
    evaluate_seed_failure,
    evaluate_slow_score,
    evaluate_workspace,
)


class SequenceModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.model = "sequence-model"

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("model called more times than expected")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def code(score: int) -> str:
    return f"```python\nSCORE = {score}\n```"


class EvolutionEngineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.project = Path(self.tempdir.name)
        self.seed = self.project / "seed.py"
        self.task = self.project / "TASK.md"
        self.workdir = self.project / ".nanoevolve"
        self.seed.write_text("SCORE = 0\n")
        self.task.write_text("# Goal\nIncrease SCORE.\n")

    def tearDown(self):
        self.tempdir.cleanup()

    def run_evolve(self, model, iterations, **overrides):
        options = {
            "seed": self.seed,
            "evaluate": evaluate_score_constant,
            "model": model,
            "task": self.task,
            "iterations": iterations,
            "workdir": self.workdir,
            "random_seed": 42,
            "timeout": 2,
        }
        options.update(overrides)
        return evolve(**options)

    def test_evaluates_seed_and_runs_successful_generations(self):
        events: list[EvolutionEvent] = []
        model = SequenceModel([code(1), code(2)])

        best = self.run_evolve(model, 2, on_event=events.append)

        archive = Archive.open(self.workdir)
        self.assertEqual(best.evaluation.score, 2.0)
        self.assertEqual([record.generation for record in archive.records], [0, 1, 2])
        self.assertEqual([record.status for record in archive.records], ["success"] * 3)
        self.assertEqual(len(model.prompts), 2)
        self.assertIn("SCORE = 0", model.prompts[0])
        self.assertTrue(any(event.type == "new_best" for event in events))

    def test_failed_mutation_consumes_generation_and_later_run_continues(self):
        model = SequenceModel(["not a code block", code(2)])

        best = self.run_evolve(model, 2)

        records = Archive.open(self.workdir).records
        self.assertEqual(best.evaluation.score, 2.0)
        self.assertEqual([record.generation for record in records], [0, 1, 2])
        self.assertEqual(records[1].status, "invalid_response")
        self.assertEqual(records[2].status, "success")

    def test_model_error_is_committed_and_does_not_stop_run(self):
        model = SequenceModel([RuntimeError("provider down"), code(3)])

        best = self.run_evolve(model, 2)

        records = Archive.open(self.workdir).records
        self.assertEqual(best.evaluation.score, 3.0)
        self.assertEqual(records[1].status, "model_error")
        self.assertIn("provider down", records[1].error)

    def test_resume_targets_total_generation_and_is_idempotent(self):
        first_model = SequenceModel([code(1)])
        self.run_evolve(first_model, 1)

        resume_model = SequenceModel([code(2), code(3)])
        best = self.run_evolve(resume_model, 3)
        self.assertEqual(best.evaluation.score, 3.0)
        self.assertEqual(len(resume_model.prompts), 2)

        no_call_model = SequenceModel([])
        repeated = self.run_evolve(no_call_model, 3)
        self.assertEqual(repeated.evaluation.score, 3.0)
        self.assertEqual(no_call_model.prompts, [])

    def test_resume_rejects_changed_task_or_seed(self):
        self.run_evolve(SequenceModel([code(1)]), 1)
        self.task.write_text("# Goal\nDifferent task.\n")

        with self.assertRaises(EvolutionError):
            self.run_evolve(SequenceModel([]), 1)

    def test_seed_failure_is_committed_and_stops_run(self):
        with self.assertRaises(EvolutionError):
            self.run_evolve(
                SequenceModel([]),
                1,
                evaluate=evaluate_seed_failure,
            )

        records = Archive.open(self.workdir).records
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].generation, 0)
        self.assertEqual(records[0].status, "evaluation_error")

    def test_multifile_search_replace_run(self):
        workspace = self.project / "seed"
        (workspace / "pkg").mkdir(parents=True)
        (workspace / "main.py").write_text("SCORE = 0\n")
        (workspace / "pkg" / "helper.py").write_text("value = 1\n")
        response = (
            "<<<<<<< SEARCH\npath: main.py\nSCORE = 0\n=======\nSCORE = 5\n"
            ">>>>>>> REPLACE\n"
        )

        best = self.run_evolve(
            SequenceModel([response]),
            1,
            seed=workspace,
            evaluate=evaluate_workspace,
            mutation_mode="search_replace",
        )

        self.assertEqual(best.evaluation.score, 5.0)
        self.assertIn("workspace/main.py", best.artifacts)
        self.assertIn("workspace/pkg/helper.py", best.artifacts)

    def test_parallel_workers_evaluate_a_generation_batch(self):
        sequential_started = time.monotonic()
        self.run_evolve(
            SequenceModel([code(1), code(2)]),
            2,
            evaluate=evaluate_slow_score,
            workdir=self.project / ".sequential",
            workers=1,
        )
        sequential_elapsed = time.monotonic() - sequential_started

        parallel_started = time.monotonic()
        best = self.run_evolve(
            SequenceModel([code(1), code(2)]),
            2,
            evaluate=evaluate_slow_score,
            workdir=self.project / ".parallel",
            workers=2,
        )
        parallel_elapsed = time.monotonic() - parallel_started

        self.assertEqual(best.evaluation.score, 2.0)
        self.assertLess(parallel_elapsed, sequential_elapsed)

    def test_prompt_includes_inspiration_and_parent_artifacts(self):
        model = SequenceModel([code(1), code(2)])

        self.run_evolve(
            model,
            2,
            inspiration_count=1,
            artifact_feedback=("stdout",),
        )

        self.assertIn("Inspiration candidates", model.prompts[1])
        self.assertIn("Artifact feedback", model.prompts[1])

    def test_legacy_archive_accepts_default_roadmap_options(self):
        archive = Archive.create(
            self.workdir,
            {
                "task_hash": "task",
                "seed_hash": "seed",
                "evaluator_hash": "evaluator",
                "model": "model",
                "random_seed": 42,
            },
        )

        _validate_resume(
            archive,
            {
                "task_hash": "task",
                "seed_hash": "seed",
                "evaluator_hash": "evaluator",
                "model": "model",
                "random_seed": 42,
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
            },
        )

    def test_single_file_run_rejects_multifile_response(self):
        model = SequenceModel(
            [
                "### FILE: seed.py\n```python\nSCORE = 1\n```\n"
                "### FILE: extra.py\n```python\nvalue = 2\n```\n"
            ]
        )

        best = self.run_evolve(model, 1)

        records = Archive.open(self.workdir).records
        self.assertEqual(best.evaluation.score, 0.0)
        self.assertEqual(records[1].status, "invalid_response")


if __name__ == "__main__":
    unittest.main()
