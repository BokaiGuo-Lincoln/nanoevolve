import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTests(unittest.TestCase):
    def setUp(self):
        self.metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())

    def test_runtime_dependencies_remain_empty(self):
        self.assertEqual(self.metadata["project"]["dependencies"], [])

    def test_truthful_classifiers_and_keywords_are_declared(self):
        project = self.metadata["project"]
        classifiers = set(project["classifiers"])

        self.assertIn("Development Status :: 3 - Alpha", classifiers)
        self.assertIn("Operating System :: OS Independent", classifiers)
        self.assertIn("Programming Language :: Python :: 3.11", classifiers)
        self.assertIn("Programming Language :: Python :: 3.12", classifiers)
        self.assertIn("Programming Language :: Python :: 3.13", classifiers)
        self.assertIn("Artificial Intelligence", project["keywords"])
        self.assertIn("evolutionary programming", project["keywords"])

    def test_unknown_identity_and_license_fields_are_absent(self):
        project = self.metadata["project"]

        for field in ("authors", "maintainers", "license", "urls"):
            self.assertNotIn(field, project)

    def test_typed_marker_is_declared_and_present(self):
        package_data = self.metadata["tool"]["setuptools"]["package-data"]

        self.assertIn("py.typed", package_data["nanoevolve"])
        self.assertTrue((ROOT / "nanoevolve" / "py.typed").is_file())

    def test_manifest_includes_contributor_material(self):
        manifest = (ROOT / "MANIFEST.in").read_text()

        for required in (
            "README.zh-CN.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "recursive-include docs",
            "recursive-include examples",
            "recursive-include scripts",
            "recursive-include tests",
            "recursive-include tasks",
        ):
            self.assertIn(required, manifest)


if __name__ == "__main__":
    unittest.main()
