import tempfile
import unittest
from pathlib import Path

from nanoevolve import EvolutionEvent, evolve
from nanoevolve.archive import Archive
from nanoevolve.engine import EvolutionError
from tests.fixtures.evaluators import evaluate_score_constant, evaluate_seed_failure


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


if __name__ == "__main__":
    unittest.main()
