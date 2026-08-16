from __future__ import annotations

import unittest

from scripts.prepare_release_notes import ReleaseNotesError, prepare_release_notes


ARCHIVE = "CharaPicker-v1.0.0-windows-x64.zip"


class ReleaseNotesTests(unittest.TestCase):
    def test_notes_include_changelog_and_distinct_trust_layers(self) -> None:
        notes = prepare_release_notes(
            "# Changelog\n\n## v1.0.0\n\n- Stable release.\n\n## v0.9.0\n\n- Old.\n",
            tag="v1.0.0",
            archive_name=ARCHIVE,
        )

        self.assertIn("- Stable release.", notes)
        self.assertNotIn("- Old.", notes)
        self.assertIn("未使用 Authenticode 签名", notes)
        self.assertIn("不用于验证发布者身份", notes)
        self.assertIn("它不是 Windows 发布者签名", notes)
        self.assertIn("Get-FileHash $archive -Algorithm SHA256", notes)
        self.assertIn(f'gh attestation verify ".\\{ARCHIVE}"', notes)

    def test_missing_changelog_section_fails(self) -> None:
        with self.assertRaisesRegex(ReleaseNotesError, "no section"):
            prepare_release_notes(
                "# Changelog\n",
                tag="v1.0.0",
                archive_name=ARCHIVE,
            )

    def test_invalid_archive_name_fails(self) -> None:
        with self.assertRaisesRegex(ReleaseNotesError, "archive name is invalid"):
            prepare_release_notes(
                "## v1.0.0\n\n- Stable release.\n",
                tag="v1.0.0",
                archive_name="unexpected.zip",
            )


if __name__ == "__main__":
    unittest.main()
