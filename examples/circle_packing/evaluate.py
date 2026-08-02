import importlib.util
import math

from nanoevolve import Evaluation


def evaluate(source_path: str) -> Evaluation:
    spec = importlib.util.spec_from_file_location("candidate", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    points = module.solve()
    if len(points) != 8:
        raise ValueError("solve() must return exactly eight points")
    normalized = []
    for point in points:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("each point must contain two coordinates")
        x, y = float(point[0]), float(point[1])
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError("coordinates must stay inside the unit square")
        normalized.append((x, y))
    minimum_distance = min(
        math.dist(left, right)
        for index, left in enumerate(normalized)
        for right in normalized[index + 1 :]
    )
    return Evaluation(
        score=minimum_distance,
        feedback=f"Minimum pairwise distance: {minimum_distance:.6f}",
        metrics={"minimum_distance": minimum_distance},
    )
