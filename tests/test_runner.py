import os
import unittest

from nanoevolve.runner import (
    EvaluatorConfigurationError,
    SubprocessRunner,
    normalize_evaluation,
    resolve_evaluator,
)
from tests.fixtures import evaluators


class EvaluationNormalizationTests(unittest.TestCase):
    def test_accepts_float_dict_and_evaluation(self):
        self.assertEqual(normalize_evaluation(1).score, 1.0)
        self.assertEqual(
            normalize_evaluation(
                {"score": 2, "feedback": "ok", "metrics": {"runtime": 3}}
            ).metrics,
            {"runtime": 3.0},
        )
        evaluation = normalize_evaluation(evaluators.evaluate_object(__file__))
        self.assertEqual(evaluation.score, 3.0)

    def test_rejects_unsupported_values(self):
        for value in (None, "1.0", {"feedback": "missing score"}):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError, KeyError)):
                    normalize_evaluation(value)


class EvaluatorResolutionTests(unittest.TestCase):
    def test_resolves_top_level_function(self):
        spec = resolve_evaluator(evaluators.evaluate_float)

        self.assertTrue(spec.path.name.endswith("evaluators.py"))
        self.assertEqual(spec.function_name, "evaluate_float")

    def test_rejects_lambda(self):
        with self.assertRaises(EvaluatorConfigurationError):
            resolve_evaluator(lambda path: 1.0)


class SubprocessRunnerTests(unittest.TestCase):
    def test_normalizes_supported_evaluator_returns(self):
        runner = SubprocessRunner(timeout=2)

        float_result = runner.run("x = 1\n", evaluators.evaluate_float)
        dict_result = runner.run("x = 1\n", evaluators.evaluate_dict)
        object_result = runner.run("x = 1\n", evaluators.evaluate_object)

        self.assertEqual(float_result.status, "success")
        self.assertGreater(float_result.evaluation.score, 0)
        self.assertIn("float evaluator stdout", float_result.stdout)
        self.assertEqual(dict_result.evaluation.feedback, "dictionary result")
        self.assertEqual(object_result.evaluation.score, 3.0)

    def test_maps_exception_and_invalid_result(self):
        runner = SubprocessRunner(timeout=2)

        error_result = runner.run("x = 1\n", evaluators.evaluate_error)
        invalid_result = runner.run("x = 1\n", evaluators.evaluate_invalid)

        self.assertEqual(error_result.status, "evaluation_error")
        self.assertIn("evaluator exploded", error_result.error)
        self.assertIn("before failure", error_result.stdout)
        self.assertEqual(invalid_result.status, "invalid_evaluation")

    def test_maps_timeout(self):
        result = SubprocessRunner(timeout=0.1).run(
            "x = 1\n", evaluators.evaluate_timeout
        )

        self.assertEqual(result.status, "evaluation_timeout")
        self.assertIsNone(result.evaluation)

    def test_filters_secret_environment_variables(self):
        names = {
            "SERVICE_API_KEY": "key",
            "SERVICE_ACCESS_TOKEN": "access",
            "SERVICE_AUTH_TOKEN": "auth",
            "SERVICE_SECRET": "secret",
            "SERVICE_PASSWORD": "password",
        }
        old_values = {name: os.environ.get(name) for name in names}
        os.environ.update(names)
        try:
            result = SubprocessRunner(timeout=2).run(
                "x = 1\n", evaluators.evaluate_environment
            )
        finally:
            for name, value in old_values.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertEqual(result.status, "success")
        self.assertEqual(result.evaluation.score, 1.0, result.evaluation.feedback)

    def test_truncates_large_stdout(self):
        result = SubprocessRunner(timeout=2, output_limit=128).run(
            "x = 1\n", evaluators.evaluate_large_output
        )

        self.assertEqual(result.status, "success")
        self.assertLessEqual(len(result.stdout.encode()), 160)
        self.assertIn("truncated", result.stdout)


if __name__ == "__main__":
    unittest.main()
