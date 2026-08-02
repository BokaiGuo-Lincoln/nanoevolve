from nanoevolve import Evaluation


def evaluate(source_path: str) -> Evaluation:
    namespace = {}
    source = open(source_path, encoding="utf-8").read()
    exec(source, namespace)
    return Evaluation(
        score=namespace["SCORE"],
        feedback="SCORE was loaded successfully.",
    )
