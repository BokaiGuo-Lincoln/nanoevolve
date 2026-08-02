from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


RecordStatus = Literal[
    "success",
    "model_error",
    "invalid_response",
    "evaluation_error",
    "evaluation_timeout",
    "invalid_evaluation",
]

RECORD_STATUSES = {
    "success",
    "model_error",
    "invalid_response",
    "evaluation_error",
    "evaluation_timeout",
    "invalid_evaluation",
}


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True)
class Evaluation:
    score: float
    feedback: str = ""
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.feedback, str):
            raise TypeError("feedback must be a string")
        normalized_metrics: dict[str, float] = {}
        for key, value in self.metrics.items():
            if not isinstance(key, str):
                raise TypeError("metric names must be strings")
            normalized_metrics[key] = _finite_number(value, f"metric {key!r}")
        object.__setattr__(self, "score", _finite_number(self.score, "score"))
        object.__setattr__(self, "metrics", normalized_metrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "feedback": self.feedback,
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Evaluation:
        return cls(
            score=value["score"],
            feedback=value.get("feedback", ""),
            metrics=value.get("metrics", {}),
        )


@dataclass(frozen=True)
class Record:
    id: str
    parent_id: str | None
    generation: int
    status: RecordStatus
    source_path: str | None
    evaluation: Evaluation | None
    error: str | None
    selection_mode: str | None = None
    generation_seed: int | None = None
    artifacts: Mapping[str, str] = field(default_factory=dict)
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("record id must not be empty")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if self.status not in RECORD_STATUSES:
            raise ValueError(f"unknown record status: {self.status}")
        if self.status == "success" and self.evaluation is None:
            raise ValueError("successful records require an evaluation")
        object.__setattr__(self, "artifacts", dict(self.artifacts))
        object.__setattr__(self, "artifact_hashes", dict(self.artifact_hashes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "status": self.status,
            "source_path": self.source_path,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "error": self.error,
            "selection_mode": self.selection_mode,
            "generation_seed": self.generation_seed,
            "artifacts": dict(self.artifacts),
            "artifact_hashes": dict(self.artifact_hashes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Record:
        raw_evaluation = value.get("evaluation")
        return cls(
            id=value["id"],
            parent_id=value.get("parent_id"),
            generation=int(value["generation"]),
            status=value["status"],
            source_path=value.get("source_path"),
            evaluation=(
                Evaluation.from_dict(raw_evaluation) if raw_evaluation is not None else None
            ),
            error=value.get("error"),
            selection_mode=value.get("selection_mode"),
            generation_seed=value.get("generation_seed"),
            artifacts=value.get("artifacts", {}),
            artifact_hashes=value.get("artifact_hashes", {}),
            created_at=value.get("created_at"),
        )


@dataclass(frozen=True)
class EvolutionEvent:
    type: str
    generation: int
    record_id: str | None
    data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.type:
            raise ValueError("event type must not be empty")
        if self.generation < 0:
            raise ValueError("event generation must be non-negative")
        object.__setattr__(self, "data", dict(self.data))
