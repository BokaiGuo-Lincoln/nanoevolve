import tempfile
import unittest
from pathlib import Path

from nanoevolve.engine import EvolutionError, read_workspace


class WorkspaceTests(unittest.TestCase):
    def test_reads_single_file_and_directory_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            single = root / "seed.py"
            single.write_text("value = 1\n")
            workspace = root / "workspace"
            (workspace / "pkg").mkdir(parents=True)
            (workspace / "main.py").write_text("from pkg import helper\n")
            (workspace / "pkg" / "helper.py").write_text("value = 2\n")

            self.assertEqual(read_workspace(single), {"seed.py": "value = 1\n"})
            self.assertEqual(
                read_workspace(workspace),
                {
                    "main.py": "from pkg import helper\n",
                    "pkg/helper.py": "value = 2\n",
                },
            )

    def test_rejects_empty_or_non_utf8_workspaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty"
            empty.mkdir()
            with self.assertRaises(EvolutionError):
                read_workspace(empty)

            binary = root / "binary"
            binary.mkdir()
            (binary / "data.bin").write_bytes(b"\xff")
            with self.assertRaises(EvolutionError):
                read_workspace(binary)

    def test_rejects_symlinks_in_seed_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.py"
            outside.write_text("secret = True\n")
            (workspace / "linked.py").symlink_to(outside)

            with self.assertRaises(EvolutionError):
                read_workspace(workspace)


if __name__ == "__main__":
    unittest.main()
