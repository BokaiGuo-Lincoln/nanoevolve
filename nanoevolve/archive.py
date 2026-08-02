from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

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
    def sqlite_path(self) -> Path:
        return self.root / "records.sqlite3"

    @property
    def backend(self) -> str:
        return str(self.metadata.get("archive_backend", "jsonl"))

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
        backend = str(metadata.get("archive_backend", "jsonl"))
        if backend == "jsonl":
            (root_path / "records.jsonl").touch()
        elif backend == "sqlite":
            with sqlite3.connect(root_path / "records.sqlite3") as connection:
                connection.execute(
                    "CREATE TABLE records (generation INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
                )
        else:
            raise ValueError(f"unknown archive backend: {backend}")
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
        if self.backend == "sqlite":
            try:
                with sqlite3.connect(self.sqlite_path) as connection:
                    rows = connection.execute(
                        "SELECT payload FROM records ORDER BY generation"
                    ).fetchall()
                return [Record.from_dict(json.loads(row[0])) for row in rows]
            except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ArchiveCorruptionError(f"invalid SQLite records: {error}") from error
        if self.backend != "jsonl":
            raise ArchiveCorruptionError(f"unknown archive backend: {self.backend}")
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
                relative = PurePosixPath(filename)
                if (
                    not filename
                    or relative.is_absolute()
                    or ".." in relative.parts
                    or "." in relative.parts
                ):
                    raise ValueError(f"unsafe artifact path: {filename}")
                raw = content.encode() if isinstance(content, str) else content
                artifact_path = temporary_path.joinpath(*relative.parts)
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                with artifact_path.open("wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                name = (
                    Path(filename).stem
                    if len(relative.parts) == 1
                    else relative.as_posix()
                )
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
            self._write_record(committed)
            self.records.append(committed)
            return committed
        finally:
            if temporary_path.exists():
                shutil.rmtree(temporary_path)

    def _write_record(self, record: Record) -> None:
        serialized = json.dumps(
            record.to_dict(), sort_keys=True, separators=(",", ":")
        )
        if self.backend == "sqlite":
            try:
                with sqlite3.connect(self.sqlite_path) as connection:
                    connection.execute(
                        "INSERT INTO records (generation, payload) VALUES (?, ?)",
                        (record.generation, serialized),
                    )
            except sqlite3.Error as error:
                raise ArchiveError(f"cannot commit SQLite record: {error}") from error
            return
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_artifact(self, record: Record, name: str) -> str:
        try:
            relative_path = record.artifacts[name]
        except KeyError as error:
            raise ArchiveError(f"record {record.id} has no artifact {name!r}") from error
        return (self.root / relative_path).read_text(encoding="utf-8")

    def successful_records(self) -> list[Record]:
        return [record for record in self.records if record.status == "success"]

    @staticmethod
    def _rank_key(record: Record, objectives: Sequence[str]) -> tuple[Any, ...]:
        values: list[float | str] = []
        for objective in objectives:
            try:
                name, direction = objective.rsplit(":", 1)
            except ValueError as error:
                raise ValueError(f"invalid objective: {objective}") from error
            if direction not in {"max", "min"}:
                raise ValueError(f"invalid objective direction: {objective}")
            if name == "score":
                value = record.evaluation.score
            else:
                try:
                    value = record.evaluation.metrics[name]
                except KeyError as error:
                    raise ArchiveError(
                        f"record {record.id} is missing objective metric {name!r}"
                    ) from error
            values.append(-value if direction == "max" else value)
        values.append(record.id)
        return tuple(values)

    def _ranked(
        self,
        records: Sequence[Record],
        objectives: Sequence[str],
    ) -> list[Record]:
        eligible: list[Record] = []
        for record in records:
            try:
                self._rank_key(record, objectives)
            except ArchiveError:
                continue
            eligible.append(record)
        if not eligible:
            raise ArchiveError("archive has no records with all selection objectives")
        return sorted(eligible, key=lambda record: self._rank_key(record, objectives))

    def best(self, objectives: Sequence[str] = ("score:max",)) -> Record:
        records = self.successful_records()
        if not records:
            raise ArchiveError("archive has no successful records")
        return self._ranked(records, objectives)[0]

    def elites(
        self,
        features: Sequence[str],
        feature_bins: Mapping[str, float],
        objectives: Sequence[str] = ("score:max",),
    ) -> list[Record]:
        return self._elites_from(
            self.successful_records(), features, feature_bins, objectives
        )

    def _elites_from(
        self,
        records: Sequence[Record],
        features: Sequence[str],
        feature_bins: Mapping[str, float],
        objectives: Sequence[str],
    ) -> list[Record]:
        if not features:
            return self._ranked(records, objectives)
        cells: dict[tuple[int, ...], Record] = {}
        for record in records:
            try:
                coordinates = tuple(
                    math.floor(record.evaluation.metrics[name] / feature_bins[name])
                    for name in features
                )
            except KeyError:
                continue
            if any(feature_bins[name] <= 0 for name in features):
                raise ValueError("feature bin widths must be positive")
            current = cells.get(coordinates)
            if current is None or self._rank_key(record, objectives) < self._rank_key(
                current, objectives
            ):
                cells[coordinates] = record
        if not cells:
            raise ArchiveError("archive has no records with all feature metrics")
        return [cells[cell] for cell in sorted(cells)]

    def select_parent(
        self,
        run_seed: int,
        generation: int,
        top_k: int = 5,
        epsilon: float = 0.2,
        objectives: Sequence[str] = ("score:max",),
        features: Sequence[str] = (),
        feature_bins: Mapping[str, float] | None = None,
        islands: int = 1,
        migration_interval: int = 0,
    ) -> tuple[Record, str, int]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon must be between 0 and 1")
        if islands <= 0:
            raise ValueError("islands must be positive")
        if migration_interval < 0:
            raise ValueError("migration_interval must be non-negative")
        records = self.successful_records()
        if not records:
            raise ArchiveError("archive has no successful parent")
        target_island = generation % islands
        migrating = islands > 1 and migration_interval > 0 and generation % migration_interval == 0
        if islands > 1 and not migrating:
            local = [record for record in records if record.island == target_island]
            if local:
                records = local
        records = (
            self._elites_from(records, features, feature_bins or {}, objectives)
            if features
            else self._ranked(records, objectives)
        )
        generation_seed = stable_generation_seed(run_seed, generation)
        rng = random.Random(generation_seed)
        suffix = ""
        if islands > 1:
            suffix = ":migration" if migrating else f":island-{target_island}"
        if rng.random() < epsilon:
            return records[rng.randrange(len(records))], "exploration" + suffix, generation_seed
        pool = records[:top_k]
        total_weight = len(pool) * (len(pool) + 1) // 2
        choice = rng.randrange(total_weight)
        cumulative = 0
        for index, record in enumerate(pool):
            cumulative += len(pool) - index
            if choice < cumulative:
                return record, "top_k" + suffix, generation_seed
        raise AssertionError("weighted selection did not return a parent")
