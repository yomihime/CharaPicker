from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_release_dependencies import ROOT_DIR, validate_release_dependencies


class ReleaseDependencyTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        for relative in (
            ".gitattributes",
            "THIRD_PARTY_NOTICES.md",
            "pyproject.toml",
            "release-dependency-inventory.json",
            "release-environment.json",
            "requirements-release-windows-py312.txt",
            "requirements.txt",
        ):
            shutil.copy2(ROOT_DIR / relative, root / relative)
        return root

    def test_committed_inventory_matches_release_lock(self) -> None:
        self.assertEqual(validate_release_dependencies(), [])

    def test_lock_inventory_version_drift_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(Path(tmp))
            inventory_path = root / "release-dependency-inventory.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["packages"][0]["version"] = "999.0.0"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

            errors = validate_release_dependencies(root)

            self.assertTrue(any("package versions differ" in error for error in errors))

    def test_private_inventory_source_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(Path(tmp))
            inventory_path = root / "release-dependency-inventory.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["packages"][0]["source"] = "C:/Users/example/private-wheel"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

            errors = validate_release_dependencies(root)

            self.assertTrue(any("absolute private path" in error for error in errors))
            self.assertTrue(any("unexpected source" in error for error in errors))

    def test_crlf_release_lock_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(Path(tmp))
            lock_path = root / "requirements-release-windows-py312.txt"
            content = lock_path.read_text(encoding="utf-8")
            lock_path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

            errors = validate_release_dependencies(root)

            self.assertTrue(any("must use LF line endings" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
