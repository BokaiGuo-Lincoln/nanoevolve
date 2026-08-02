import math
import unittest
from dataclasses import FrozenInstanceError

from nanoevolve import Evaluation, EvolutionEvent, Record


class EvaluationTests(unittest.TestCase):
    def test_normalizes_numeric_values(self):
        evaluation = Evaluation(
            score=3,
            feedback="ok",
            metrics={"runtime": 4, "quality": 0.5},
        )

        self.assertEqual(evaluation.score, 3.0)
        self.assertEqual(evaluation.metrics, {"runtime": 4.0, "quality": 0.5})

    def test_rejects_non_finite_score(self):
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Evaluation(score=value)

    def test_rejects_boolean_score_and_invalid_metrics(self):
        with self.assertRaises(TypeError):
            Evaluation(score=True)
        with self.assertRaises(TypeError):
            Evaluation(score=1.0, metrics={"runtime": "fast"})
        with self.assertRaises(ValueError):
            Evaluation(score=1.0, metrics={"runtime": math.nan})

    def test_is_frozen(self):
        evaluation = Evaluation(score=1.0)

        with self.assertRaises(FrozenInstanceError):
            evaluation.score = 2.0


class RecordTests(unittest.TestCase):
    def test_round_trips_through_json_dict(self):
        record = Record(
            id="abc",
            parent_id="seed",
            generation=4,
            status="success",
            source_path="candidates/abc/source.py",
            evaluation=Evaluation(0.75, "better", {"runtime": 2.0}),
            error=None,
            selection_mode="top_k",
            generation_seed=123,
            artifacts={"prompt": "candidates/abc/prompt.txt"},
        )

        self.assertEqual(Record.from_dict(record.to_dict()), record)

    def test_round_trips_quality_diversity_metadata(self):
        record = Record(
            id="candidate",
            parent_id=None,
            generation=0,
            status="success",
            source_path="source.py",
            evaluation=Evaluation(1),
            error=None,
            island=2,
            feature_coordinates=(3, -1),
        )

        self.assertEqual(Record.from_dict(record.to_dict()), record)

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            Record(
                id="abc",
                parent_id=None,
                generation=1,
                status="unknown",
                source_path=None,
                evaluation=None,
                error="bad",
            )

    def test_event_is_frozen(self):
        event = EvolutionEvent("generation_started", 1, None, {"parent": "seed"})

        with self.assertRaises(FrozenInstanceError):
            event.generation = 2


if __name__ == "__main__":
    unittest.main()
