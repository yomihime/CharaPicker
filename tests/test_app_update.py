from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils.app_update import (
    APP_NAME,
    AppVersion,
    UpdateDownloadError,
    UpdatePackageUnavailableError,
    _extract_update_archive,
    _read_expected_checksum,
    check_for_update,
)


def _release_payload(
    tag: str,
    *,
    prerelease: bool,
    with_checksum: bool = True,
) -> dict[str, object]:
    version_tag = tag.removeprefix("v")
    archive_name = f"{APP_NAME}-v{version_tag}-windows-x64.zip"
    assets: list[dict[str, object]] = [
        {
            "name": archive_name,
            "browser_download_url": f"https://github.com/example/{archive_name}",
            "size": 123,
        }
    ]
    if with_checksum:
        assets.append(
            {
                "name": f"{archive_name}.sha256",
                "browser_download_url": f"https://github.com/example/{archive_name}.sha256",
                "size": 80,
            }
        )
    return {
        "tag_name": tag,
        "name": tag,
        "html_url": f"https://github.com/example/releases/{tag}",
        "body": "notes",
        "draft": False,
        "prerelease": prerelease,
        "assets": assets,
    }


class AppVersionTests(unittest.TestCase):
    def test_release_stages_are_ordered(self) -> None:
        versions = [
            AppVersion.parse("v1.0.0-alpha"),
            AppVersion.parse("1.0.0-alpha.1"),
            AppVersion.parse("1.0.0-beta"),
            AppVersion.parse("1.0.0-rc.2"),
            AppVersion.parse("1.0.0"),
        ]

        self.assertEqual(sorted(reversed(versions)), versions)

    def test_higher_semantic_version_wins_over_release_stage(self) -> None:
        self.assertGreater(AppVersion.parse("0.9.0-alpha"), AppVersion.parse("0.8.9"))

    def test_public_tag_omits_release_suffix(self) -> None:
        self.assertEqual(AppVersion.parse("v1.0.0").public_tag, "1.0.0")
        self.assertEqual(AppVersion.parse("v1.0.0-rc.1").public_tag, "1.0.0-rc.1")


class UpdateCheckTests(unittest.TestCase):
    @patch("utils.app_update.read_json")
    def test_stable_channel_excludes_prereleases(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v0.9.0-beta", prerelease=True),
            _release_payload("v0.8.1", prerelease=False),
        ]

        release = check_for_update(include_prereleases=False)

        self.assertIsNotNone(release)
        self.assertEqual(release.version.public_tag, "0.8.1")

    @patch("utils.app_update.read_json")
    def test_test_channel_includes_prereleases(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v0.9.0-beta", prerelease=True),
            _release_payload("v0.8.1", prerelease=False),
        ]

        release = check_for_update(include_prereleases=True)

        self.assertIsNotNone(release)
        self.assertEqual(release.version.public_tag, "0.9.0-beta")

    @patch("utils.app_update.read_json")
    def test_newer_release_requires_archive_and_checksum(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v0.9.0-beta", prerelease=True, with_checksum=False)
        ]

        with self.assertRaises(UpdatePackageUnavailableError):
            check_for_update(include_prereleases=True)

    @patch("utils.app_update.read_json")
    def test_current_or_older_release_is_not_an_update(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v0.8.0-beta", prerelease=True),
            _release_payload("v0.7.0", prerelease=False),
        ]

        self.assertIsNone(check_for_update(include_prereleases=True))


class UpdateArchiveTests(unittest.TestCase):
    def test_extract_update_archive_accepts_expected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive_path = root / "update.zip"
            extract_dir = root / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("CharaPicker/CharaPicker.exe", b"new")
                archive.writestr("CharaPicker/CharaPickerUpdater.exe", b"updater")

            _extract_update_archive(archive_path, extract_dir)

            self.assertEqual(
                (extract_dir / "CharaPicker" / "CharaPicker.exe").read_bytes(),
                b"new",
            )

    def test_extract_update_archive_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive_path = root / "update.zip"
            extract_dir = root / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("CharaPicker/../outside.txt", b"unsafe")

            with self.assertRaises(UpdateDownloadError):
                _extract_update_archive(archive_path, extract_dir)

    def test_checksum_must_match_archive_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            checksum_path = Path(temp_name) / "update.sha256"
            checksum_path.write_text(f"{'a' * 64}  other.zip\n", encoding="ascii")

            with self.assertRaises(UpdateDownloadError):
                _read_expected_checksum(checksum_path, "expected.zip")


if __name__ == "__main__":
    unittest.main()
