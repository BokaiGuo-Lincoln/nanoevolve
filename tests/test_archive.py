import json
import tempfile
import unittest
from pathlib import Path

from nanoevolve import Evaluation, Record
from nanoevolve.archive import (
    Archive,
    ArchiveCorruptionError,
    ArchiveExistsError,
    stable_generation_seed,
)


def success_record(record_id: str, generation: int, score: float) -> Record:
    return Record(
        id=record_id,
        parent_id=None if generation == 0 else "seed",
        generation=generation,
        status="success",
        source_path=None,
        evaluation=Evaluation(score),
        error=None,
    )


def quality_record(
    record_id: str,
    parent_id: str | None,
    generation: int,
    score: float,
    *,
    metrics: dict[str, float] | None = None,
    island: int = 0,
) -> Record:
    return Record(
        id=record_id,
        parent_id=parent_id,
        generation=generation,
        status="success",
        source_path=None,
        evaluation=Evaluation(score, metrics=metrics or {}),
        error=None,
        island=island,
    )


class ArchivePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / ".nanoevolve"

    def tearDown(self):
        self.tempdir.cleanup()

    def create_archive(self) -> Archive:
        return Archive.create(
            self.root,
            {
                "format_version": 1,
                "run_id": "run-1",
                "random_seed": 42,
                "iterations_requested": 10,
            },
        )

    def test_create_refuses_existing_archive(self):
        self.create_archive()

        with self.assertRaises(ArchiveExistsError):
            Archive.create(self.root, {"format_version": 1})

    def test_commit_writes_artifacts_before_reopenable_record(self):
        archive = self.create_archive()

        committed = archive.commit(
            success_record("abc", 0, 0.5),
            {
                "source.py": "value = 1\n",
                "prompt.txt": "prompt",
            },
        )

        self.assertEqual(committed.source_path, "candidates/abc/source.py")
        self.assertEqual(
            committed.artifacts["prompt"], "candidates/abc/prompt.txt"
        )
        reopened = Archive.open(self.root)
        self.assertEqual(reopened.records, [committed])
        self.assertEqual(reopened.read_artifact(committed, "source"), "value = 1\n")

    def test_open_discards_only_truncated_final_json_line(self):
        archive = self.create_archive()
        archive.commit(success_record("seed", 0, 0.1), {"source.py": "x = 1\n"})
        with archive.records_path.open("ab") as handle:
            handle.write(b'{"id":"partial"')

        reopened = Archive.open(self.root)

        self.assertEqual([record.id for record in reopened.records], ["seed"])
        self.assertTrue(archive.records_path.read_bytes().endswith(b"\n"))

    def test_open_normalizes_valid_final_line_without_newline(self):
        archive = self.create_archive()
        archive.commit(success_record("seed", 0, 0.1), {"source.py": "x = 1\n"})
        archive.records_path.write_bytes(archive.records_path.read_bytes().rstrip(b"\n"))

        reopened = Archive.open(self.root)
        reopened.commit(success_record("next", 1, 0.2), {"source.py": "x = 2\n"})

        self.assertEqual(
            [record.id for record in Archive.open(self.root).records],
            ["seed", "next"],
        )

    def test_open_rejects_middle_or_complete_line_corruption(self):
        archive = self.create_archive()
        archive.records_path.write_text('{bad}\n{"also":"bad"}\n')

        with self.assertRaises(ArchiveCorruptionError):
            Archive.open(self.root)

    def test_open_detects_modified_artifact(self):
        archive = self.create_archive()
        record = archive.commit(
            success_record("seed", 0, 0.1),
            {"source.py": "x = 1\n"},
        )
        (self.root / record.source_path).write_text("x = 999\n")

        with self.assertRaises(ArchiveCorruptionError):
            Archive.open(self.root)

    def test_open_removes_uncommitted_candidate_directories(self):
        archive = self.create_archive()
        orphan = archive.candidates_path / "orphan"
        orphan.mkdir()
        (orphan / "source.py").write_text("x = 1\n")
        temporary = archive.candidates_path / ".tmp-leftover"
        temporary.mkdir()

        Archive.open(self.root)

        self.assertFalse(orphan.exists())
        self.assertFalse(temporary.exists())

    def test_open_rejects_missing_parent_and_duplicate_generation(self):
        archive = self.create_archive()
        archive.commit(success_record("seed", 0, 0.1), {"source.py": "x = 1\n"})
        orphan = success_record("orphan", 1, 0.2)
        orphan = Record(
            id=orphan.id,
            parent_id="missing",
            generation=orphan.generation,
            status=orphan.status,
            source_path=orphan.source_path,
            evaluation=orphan.evaluation,
            error=orphan.error,
        )
        archive.commit(orphan, {"source.py": "x = 2\n"})

        with self.assertRaises(ArchiveCorruptionError):
            Archive.open(self.root)

        second_root = Path(self.tempdir.name) / ".duplicate"
        duplicate = Archive.create(second_root, {"format_version": 1})
        duplicate.commit(success_record("first", 0, 0.1), {"source.py": "x = 1\n"})
        duplicate.commit(success_record("second", 0, 0.2), {"source.py": "x = 2\n"})

        with self.assertRaises(ArchiveCorruptionError):
            Archive.open(second_root)


class ArchiveSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / ".nanoevolve"
        self.archive = Archive.create(
            self.root,
            {
                "format_version": 1,
                "run_id": "run-1",
                "random_seed": 42,
                "iterations_requested": 10,
            },
        )
        for record_id, generation, score in (
            ("seed", 0, 0.1),
            ("mid", 1, 0.5),
            ("best", 2, 0.9),
        ):
            self.archive.commit(
                success_record(record_id, generation, score),
                {"source.py": f"score = {score}\n"},
            )
        self.archive.commit(
            Record(
                id="failed",
                parent_id="best",
                generation=3,
                status="evaluation_error",
                source_path=None,
                evaluation=None,
                error="boom",
            ),
            {"response.txt": "bad"},
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_best_excludes_failed_records(self):
        self.assertEqual(self.archive.best().id, "best")

    def test_top_one_always_selects_best(self):
        parent, mode, generation_seed = self.archive.select_parent(
            run_seed=42,
            generation=8,
            top_k=1,
            epsilon=0.0,
        )

        self.assertEqual(parent.id, "best")
        self.assertEqual(mode, "top_k")
        self.assertEqual(generation_seed, stable_generation_seed(42, 8))

    def test_selection_is_reproducible(self):
        first = self.archive.select_parent(42, 7, top_k=3, epsilon=0.4)
        second = self.archive.select_parent(42, 7, top_k=3, epsilon=0.4)

        self.assertEqual(first, second)

    def test_exploration_only_samples_successful_records(self):
        parent, mode, _ = self.archive.select_parent(
            run_seed=42,
            generation=9,
            top_k=3,
            epsilon=1.0,
        )

        self.assertEqual(mode, "exploration")
        self.assertIn(parent.id, {"seed", "mid", "best"})

    def test_multi_objective_best_supports_minimize_metrics(self):
        root = Path(self.tempdir.name) / ".objectives"
        archive = Archive.create(root, {"run_id": "run"})
        archive.commit(
            quality_record("fast", None, 0, 5, metrics={"runtime": 2}),
            {"source.py": "x = 1\n"},
        )
        archive.commit(
            quality_record("slow", "fast", 1, 5, metrics={"runtime": 8}),
            {"source.py": "x = 2\n"},
        )

        self.assertEqual(
            archive.best(("score:max", "runtime:min")).id,
            "fast",
        )

    def test_map_elites_keeps_one_parent_per_feature_cell(self):
        root = Path(self.tempdir.name) / ".elites"
        archive = Archive.create(root, {"run_id": "run"})
        for record in (
            quality_record("a", None, 0, 1, metrics={"size": 1}),
            quality_record("b", "a", 1, 3, metrics={"size": 2}),
            quality_record("c", "b", 2, 2, metrics={"size": 12}),
        ):
            archive.commit(record, {"source.py": f"x = {record.generation}\n"})

        elites = archive.elites(("size",), {"size": 10.0})

        self.assertEqual({record.id for record in elites}, {"b", "c"})

    def test_island_selection_is_local_except_on_migration(self):
        root = Path(self.tempdir.name) / ".islands"
        archive = Archive.create(root, {"run_id": "run"})
        archive.commit(
            quality_record("zero", None, 0, 1, island=0),
            {"source.py": "x = 0\n"},
        )
        archive.commit(
            quality_record("one", "zero", 1, 9, island=1),
            {"source.py": "x = 1\n"},
        )

        local, local_mode, _ = archive.select_parent(
            42, 2, islands=2, migration_interval=0, epsilon=0, top_k=1
        )
        migrated, migration_mode, _ = archive.select_parent(
            42, 2, islands=2, migration_interval=2, epsilon=0, top_k=1
        )

        self.assertEqual(local.id, "zero")
        self.assertEqual(local_mode, "top_k:island-0")
        self.assertEqual(migrated.id, "one")
        self.assertEqual(migration_mode, "top_k:migration")

    def test_map_elites_is_computed_within_the_target_island(self):
        root = Path(self.tempdir.name) / ".island-elites"
        archive = Archive.create(root, {"run_id": "run"})
        archive.commit(
            quality_record("zero", None, 0, 2, metrics={"size": 1}, island=0),
            {"source.py": "x = 0\n"},
        )
        archive.commit(
            quality_record("one", "zero", 1, 9, metrics={"size": 1}, island=1),
            {"source.py": "x = 1\n"},
        )

        selected, mode, _ = archive.select_parent(
            42,
            2,
            top_k=1,
            epsilon=0,
            features=("size",),
            feature_bins={"size": 10},
            islands=2,
        )

        self.assertEqual(selected.id, "zero")
        self.assertEqual(mode, "top_k:island-0")


class SQLiteArchiveTests(unittest.TestCase):
    def test_sqlite_backend_reopens_committed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "archive"
            archive = Archive.create(
                root, {"run_id": "run", "archive_backend": "sqlite"}
            )
            archive.commit(
                quality_record("seed", None, 0, 1),
                {"source.py": "x = 1\n"},
            )

            reopened = Archive.open(root)

            self.assertEqual(reopened.metadata["archive_backend"], "sqlite")
            self.assertEqual(reopened.best().id, "seed")
            self.assertTrue((root / "records.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
