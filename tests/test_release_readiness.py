from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_release_readiness import ROOT_DIR, validate_repository


class ReleaseReadinessTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        for relative in (
            ".github/workflows/build.yml",
            "CHANGELOG.md",
            "build.bat",
            "pyproject.toml",
            "release-environment.json",
            "requirements-release-windows-py312.txt",
            "README.md",
            "docs/readme/README.zh_TW.md",
            "docs/readme/README.en_US.md",
            "docs/readme/README.ja_JP.md",
        ):
            source = ROOT_DIR / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return root

    def test_current_repository_metadata_is_consistent(self) -> None:
        self.assertEqual(validate_repository(tracked_files={"README.md"}), [])

    def test_project_version_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(Path(tmp))
            project = root / "pyproject.toml"
            project.write_text(
                project.read_text(encoding="utf-8").replace(
                    'version = "1.0.2"',
                    'version = "9.9.9"',
                ),
                encoding="utf-8",
            )

            errors = validate_repository(root, tracked_files={"README.md"})

            self.assertTrue(any("pyproject.toml version mismatch" in error for error in errors))

    def test_movable_action_reference_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(Path(tmp))
            workflow = root / ".github" / "workflows" / "build.yml"
            workflow.write_text(
                re.sub(
                    r"actions/checkout@[0-9a-f]{40}",
                    "actions/checkout@v7",
                    workflow.read_text(encoding="utf-8"),
                ),
                encoding="utf-8",
            )

            errors = validate_repository(root, tracked_files={"README.md"})

            self.assertTrue(any("not pinned" in error for error in errors))

    def test_runtime_private_paths_are_reported(self) -> None:
        errors = validate_repository(
            tracked_files={
                "README.md",
                "config.yaml.bak",
                "private/card.json.bak",
                "projects/private-project/config.json",
                "signing.pfx",
            }
        )

        self.assertTrue(any("config.yaml.bak" in error for error in errors))
        self.assertTrue(any("private/card.json.bak" in error for error in errors))
        self.assertTrue(any("projects/private-project" in error for error in errors))
        self.assertTrue(any("signing.pfx" in error for error in errors))

    def test_final_tag_rejects_stale_readmes(self) -> None:
        stale_markers = {
            "README.md": "当前处于 1.0 RC",
            "docs/readme/README.zh_TW.md": "目前處於 1.0 RC",
            "docs/readme/README.en_US.md": "Currently in the 1.0 RC",
            "docs/readme/README.ja_JP.md": "現在は 1.0 RC",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(Path(tmp))
            for relative, marker in stale_markers.items():
                path = root / relative
                path.write_text(
                    f"{path.read_text(encoding='utf-8')}\n{marker}\n",
                    encoding="utf-8",
                )

            errors = validate_repository(root, tag="v1.0.0", tracked_files={"README.md"})

            self.assertEqual(sum("stale RC status" in error for error in errors), 4)


if __name__ == "__main__":
    unittest.main()
