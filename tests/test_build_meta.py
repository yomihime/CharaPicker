from __future__ import annotations

import unittest

from scripts.build_meta import _build_meta, _parse_args, _validate
from utils.app_metadata import format_version_tag


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

        self.assertEqual(_validate(meta), [])
        self.assertEqual(meta.version, "1.0.0")
        self.assertEqual(meta.stage, "rc.1")
        self.assertEqual(meta.version_tag, "1.0.0-rc.1")
        self.assertEqual(
            meta.zip_name,
            "CharaPicker-v1.0.0-rc.1-windows-x64.zip",
        )

    def test_suffixless_tag_is_a_release(self) -> None:
        meta = self._meta("--tag=v1.0.0")

        self.assertEqual(_validate(meta), [])
        self.assertEqual(meta.version, "1.0.0")
        self.assertEqual(meta.stage, "release")
        self.assertEqual(meta.version_tag, "1.0.0")
        self.assertEqual(
            meta.zip_name,
            "CharaPicker-v1.0.0-windows-x64.zip",
        )

    def test_explicit_release_stage_uses_suffixless_artifact_name(self) -> None:
        meta = self._meta("--tag=v1.0.0-release")

        self.assertEqual(_validate(meta), [])
        self.assertEqual(meta.stage, "release")
        self.assertEqual(meta.version_tag, "1.0.0")
        self.assertEqual(
            meta.zip_name,
            "CharaPicker-v1.0.0-windows-x64.zip",
        )

    def test_local_build_overrides_release_stage(self) -> None:
        meta = self._meta("--tag=v1.0.0", "--local")

        self.assertEqual(_validate(meta), [])
        self.assertEqual(meta.stage, "local")
        self.assertEqual(meta.version_tag, "1.0.0-local")
        self.assertEqual(
            meta.zip_name,
            "CharaPicker-v1.0.0-local-windows-x64.zip",
        )

    def test_runtime_release_label_is_suffixless(self) -> None:
        self.assertEqual(format_version_tag("1.0.0", "release"), "1.0.0")
        self.assertEqual(format_version_tag("1.0.0", "rc"), "1.0.0-rc")


if __name__ == "__main__":
    unittest.main()
