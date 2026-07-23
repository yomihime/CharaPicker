from __future__ import annotations

import json
import unittest

from scripts.build_meta import ROOT_DIR, _build_meta, _parse_args, _validate
from utils.app_metadata import APP_RELEASE_STAGE, APP_VERSION, format_version_tag


class BuildMetadataTests(unittest.TestCase):
    def _meta(self, *args: str):
        return _build_meta(
            _parse_args(
                [
                    *args,
                    "--platform=windows",
                    "--arch=x64",
                ]
            )
        )

    def test_rc_tag_keeps_prerelease_suffix(self) -> None:
        meta = self._meta("--tag=v1.0.0-rc.1")

        self.assertEqual(meta.version, "1.0.0")
        self.assertEqual(meta.stage, "rc.1")
        self.assertEqual(meta.version_tag, "1.0.0-rc.1")

    def test_suffixless_tag_is_a_release(self) -> None:
        meta = self._meta("--tag=v1.0.0")

        self.assertEqual(meta.version, "1.0.0")
        self.assertEqual(meta.stage, "release")
        self.assertEqual(meta.version_tag, "1.0.0")

    def test_explicit_release_stage_uses_suffixless_version_tag(self) -> None:
        meta = self._meta("--tag=v1.0.0-release")

        self.assertEqual(meta.stage, "release")
        self.assertEqual(meta.version_tag, "1.0.0")

    def test_local_build_overrides_release_stage(self) -> None:
        meta = self._meta("--tag=v1.0.0", "--local")

        self.assertEqual(_validate(meta), [])
        self.assertEqual(meta.stage, "local")
        self.assertEqual(meta.version_tag, "1.0.0-local")

    def test_runtime_release_label_is_suffixless(self) -> None:
        self.assertEqual(format_version_tag("1.0.0", "release"), "1.0.0")
        self.assertEqual(format_version_tag("1.0.0", "rc"), "1.0.0-rc")

    def test_non_local_build_requires_source_metadata_alignment(self) -> None:
        mismatched_version = "999.0.0" if APP_VERSION != "999.0.0" else "998.0.0"
        meta = self._meta(
            f"--version={mismatched_version}",
            f"--stage={APP_RELEASE_STAGE}",
        )

        errors = _validate(meta)

        self.assertTrue(any("APP_VERSION" in error for error in errors))

    def test_non_local_build_requires_source_stage_alignment(self) -> None:
        mismatched_stage = "alpha" if APP_RELEASE_STAGE.lower() != "alpha" else "beta"
        meta = self._meta(
            f"--version={APP_VERSION}",
            f"--stage={mismatched_stage}",
        )

        errors = _validate(meta)

        self.assertTrue(any("APP_RELEASE_STAGE" in error for error in errors))

    def test_current_source_metadata_is_valid(self) -> None:
        meta = self._meta(
            f"--version={APP_VERSION}",
            f"--stage={APP_RELEASE_STAGE}",
        )

        self.assertEqual(_validate(meta), [])

    def test_batch_composes_archive_name_from_metadata(self) -> None:
        batch = (ROOT_DIR / "build.bat").read_text(encoding="utf-8")

        self.assertIn(
            'set "ZIP_NAME=%APP_NAME%-v%VERSION_TAG%-%PLATFORM_TAG%-%ARCH_TAG%.zip"',
            batch,
        )
        self.assertNotIn('set "ZIP_NAME=CharaPicker-', batch)

    def test_build_packages_standalone_update_helper(self) -> None:
        batch = (ROOT_DIR / "build.bat").read_text(encoding="utf-8")

        self.assertIn("PyInstaller --noconfirm --clean updater.spec", batch)
        self.assertIn(
            '"%DIST_DIR%\\%APP_NAME%Updater.exe" '
            '"%DIST_DIR%\\%APP_NAME%\\%APP_NAME%Updater.exe"',
            batch,
        )

    def test_release_workflow_publishes_checksums(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "build.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Get-FileHash", workflow)
        self.assertIn("release/*.sha256", workflow)

    def test_about_version_messages_use_runtime_placeholder(self) -> None:
        for locale in ("zh_CN", "zh_TW", "en_US", "ja_JP"):
            payload = json.loads(
                (ROOT_DIR / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
            )
            self.assertIn("{version}", payload["about.version"])


if __name__ == "__main__":
    unittest.main()
