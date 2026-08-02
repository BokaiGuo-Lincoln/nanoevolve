from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .types import Record


class ArchiveError(RuntimeError):
    pass


class ArchiveExistsError(ArchiveError):
    pass


class ArchiveCorruptionError(ArchiveError):
    pass


def stable_generation_seed(run_seed: int, generation: int) -> int:
    digest = hashlib.sha256(f"{run_seed}:{generation}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class Archive:
    def __init__(self, root: Path, metadata: Mapping[str, Any], records: list[Record]):
        self.root = root
        self.metadata = dict(metadata)
        self.records = records

    @property
    def run_path(self) -> Path:
        return self.root / "run.json"

    @property
    def records_path(self) -> Path:
        return self.root / "records.jsonl"

    @property
    def candidates_path(self) -> Path:
        return self.root / "candidates"

    @classmethod
    def create(cls, root: str | Path, metadata: Mapping[str, Any]) -> Archive:
        root_path = Path(root)
        if root_path.exists():
            raise ArchiveExistsError(f"archive already exists: {root_path}")
        root_path.mkdir(parents=True)
        (root_path / "candidates").mkdir()
        run_path = root_path / "run.json"
        with run_path.open("w", encoding="utf-8") as handle:
            json.dump(dict(metadata), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        records_path = root_path / "records.jsonl"
        records_path.touch()
        return cls(root_path, metadata, [])

    @classmethod
    def open(cls, root: str | Path) -> Archive:
        root_path = Path(root)
        try:
            metadata = json.loads((root_path / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ArchiveCorruptionError(f"invalid run metadata: {error}") from error
        archive = cls(root_path, metadata, [])
        archive.records = archive._load_records()
        archive._verify_record_chain()
        archive._clean_uncommitted_directories()
        archive._verify_artifacts()
        return archive

    def _load_records(self) -> list[Record]:
        try:
            raw = self.records_path.read_bytes()
        except OSError as error:
            raise ArchiveCorruptionError(f"cannot read records: {error}") from error
        if not raw:
            return []
        lines = raw.splitlines(keepends=True)
        records: list[Record] = []
        valid_length = 0
        for index, line in enumerate(lines):
            try:
                payload = json.loads(line)
                record = Record.from_dict(payload)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                is_truncated_tail = index == len(lines) - 1 and not raw.endswith(b"\n")
                if not is_truncated_tail:
                    raise ArchiveCorruptionError(
                        f"invalid records line {index + 1}: {error}"
                    ) from error
                with self.records_path.open("r+b") as handle:
                    handle.truncate(valid_length)
                    handle.flush()
                    os.fsync(handle.fileno())
                break
            records.append(record)
            valid_length += len(line)
        if records and not self.records_path.read_bytes().endswith(b"\n"):
            with self.records_path.open("ab") as handle:
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
        return records

    def _verify_record_chain(self) -> None:
        by_id: dict[str, Record] = {}
        generations: set[int] = set()
        for expected_generation, record in enumerate(self.records):
            if record.id in by_id:
                raise ArchiveCorruptionError(f"duplicate record id: {record.id}")
            if record.generation in generations:
                raise ArchiveCorruptionError(
                    f"duplicate generation: {record.generation}"
                )
            if record.generation != expected_generation:
                raise ArchiveCorruptionError(
                    f"expected generation {expected_generation}, found {record.generation}"
                )
            if record.generation == 0:
                if record.parent_id is not None:
                    raise ArchiveCorruptionError("generation 0 must not have a parent")
            else:
                parent = by_id.get(record.parent_id or "")
                if parent is None:
                    raise ArchiveCorruptionError(
                        f"record {record.id} has missing parent {record.parent_id}"
                    )
                if parent.status != "success":
                    raise ArchiveCorruptionError(
                        f"record {record.id} uses unsuccessful parent {parent.id}"
                    )
            by_id[record.id] = record
            generations.add(record.generation)

    def _clean_uncommitted_directories(self) -> None:
        committed = {record.id for record in self.records}
        if not self.candidates_path.exists():
            raise ArchiveCorruptionError("candidate directory is missing")
        for path in self.candidates_path.iterdir():
            if path.is_dir() and (path.name.startswith(".tmp-") or path.name not in committed):
                shutil.rmtree(path)

    def _verify_artifacts(self) -> None:
        for record in self.records:
            for name, relative_path in record.artifacts.items():
                path = self.root / relative_path
                if not path.is_file():
                    raise ArchiveCorruptionError(
                        f"record {record.id} artifact {name!r} is missing"
                    )
                expected = record.artifact_hashes.get(name)
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if expected != actual:
                    raise ArchiveCorruptionError(
                        f"record {record.id} artifact {name!r} hash mismatch"
                    )

    def commit(
        self,
        record: Record,
        artifacts: Mapping[str, str | bytes],
    ) -> Record:
        if any(existing.id == record.id for existing in self.records):
            raise ArchiveError(f"record already exists: {record.id}")
        temporary_path = Path(
            tempfile.mkdtemp(prefix=".tmp-", dir=self.candidates_path)
        )
        artifact_paths: dict[str, str] = {}
        artifact_hashes: dict[str, str] = {}
        try:
            for filename, content in artifacts.items():
                if Path(filename).name != filename:
                    raise ValueError(f"artifact filename must be a basename: {filename}")
                raw = content.encode() if isinstance(content, str) else content
                artifact_path = temporary_path / filename
                with artifact_path.open("wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                name = Path(filename).stem
                artifact_paths[name] = f"candidates/{record.id}/{filename}"
                artifact_hashes[name] = hashlib.sha256(raw).hexdigest()

            final_path = self.candidates_path / record.id
            if final_path.exists():
                raise ArchiveError(f"candidate directory already exists: {record.id}")
            os.replace(temporary_path, final_path)

            committed = replace(
                record,
                source_path=artifact_paths.get("source"),
                artifacts=artifact_paths,
                artifact_hashes=artifact_hashes,
            )
            serialized = json.dumps(
                committed.to_dict(), sort_keys=True, separators=(",", ":")
            )
            with self.records_path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.records.append(committed)
            return committed
        finally:
            if temporary_path.exists():
                shutil.rmtree(temporary_path)

    def read_artifact(self, record: Record, name: str) -> str:
        try:
            relative_path = record.artifacts[name]
        except KeyError as error:
            raise ArchiveError(f"record {record.id} has no artifact {name!r}") from error
        return (self.root / relative_path).read_text(encoding="utf-8")

    def successful_records(self) -> list[Record]:
        return [record for record in self.records if record.status == "success"]

    def best(self) -> Record:
        records = self.successful_records()
        if not records:
            raise ArchiveError("archive has no successful records")
        return min(records, key=lambda record: (-record.evaluation.score, record.id))

    def select_parent(
        self,
        run_seed: int,
        generation: int,
        top_k: int = 5,
        epsilon: float = 0.2,
    ) -> tuple[Record, str, int]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon must be between 0 and 1")
        records = sorted(
            self.successful_records(),
            key=lambda record: (-record.evaluation.score, record.id),
        )
        if not records:
            raise ArchiveError("archive has no successful parent")
        generation_seed = stable_generation_seed(run_seed, generation)
        rng = random.Random(generation_seed)
        if rng.random() < epsilon:
            return records[rng.randrange(len(records))], "exploration", generation_seed
        pool = records[:top_k]
        total_weight = len(pool) * (len(pool) + 1) // 2
        choice = rng.randrange(total_weight)
        cumulative = 0
        for index, record in enumerate(pool):
            cumulative += len(pool) - index
            if choice < cumulative:
                return record, "top_k", generation_seed
        raise AssertionError("weighted selection did not return a parent")
