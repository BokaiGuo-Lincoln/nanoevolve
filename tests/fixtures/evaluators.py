import os
import time

from nanoevolve import Evaluation


def evaluate_float(source_path: str):
    print("float evaluator stdout")
    return float(len(open(source_path, encoding="utf-8").read()))


def evaluate_dict(source_path: str):
    return {
        "score": 2,
        "feedback": "dictionary result",
        "metrics": {"length": len(open(source_path, encoding="utf-8").read())},
    }


def evaluate_object(source_path: str):
    return Evaluation(3, "object result", {"files": 1})


def evaluate_error(source_path: str):
    print("before failure")
    raise RuntimeError("evaluator exploded")


def evaluate_invalid(source_path: str):
    return {"score": "excellent"}


def evaluate_timeout(source_path: str):
    time.sleep(2)
    return 1.0


def evaluate_environment(source_path: str):
    leaked = [
        key
        for key in os.environ
        if any(token in key.upper() for token in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN", "SECRET", "PASSWORD"))
    ]
    return Evaluation(1.0 if not leaked else 0.0, feedback=",".join(leaked))


def evaluate_large_output(source_path: str):
    print("x" * 10000)
    return 1.0


def evaluate_score_constant(source_path: str):
    namespace = {}
    exec(open(source_path, encoding="utf-8").read(), namespace)
    return Evaluation(float(namespace["SCORE"]), feedback="score loaded")


def evaluate_seed_failure(source_path: str):
    raise RuntimeError("seed cannot be evaluated")
