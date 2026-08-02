import importlib.metadata
import subprocess
import sys
import unittest

import nanoevolve
from nanoevolve.cli import main


class VersionTests(unittest.TestCase):
    def test_exported_version_is_non_empty(self):
        self.assertIsInstance(nanoevolve.__version__, str)
        self.assertTrue(nanoevolve.__version__)

    def test_exported_version_matches_installed_metadata_when_available(self):
        try:
            installed = importlib.metadata.version("nanoevolve")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("package metadata is unavailable in a raw source checkout")

        self.assertEqual(nanoevolve.__version__, installed)

    def test_cli_version_exits_successfully(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)

    def test_module_entrypoint_prints_version(self):
        completed = subprocess.run(
            [sys.executable, "-m", "nanoevolve", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(nanoevolve.__version__, completed.stdout)


if __name__ == "__main__":
    unittest.main()
