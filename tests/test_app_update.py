from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils.app_update import (
    APP_NAME,
    UPDATE_ACK_ENV,
    AppVersion,
    PreparedUpdate,
    UpdateDownloadError,
    UpdateLaunchError,
    UpdatePackageUnavailableError,
    _extract_update_archive,
    _read_expected_checksum,
    _resolve_update_payload_dir,
    acknowledge_update_startup,
    check_for_update,
    launch_prepared_update,
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
            "browser_download_url": (
                f"https://github.com/yomihime/CharaPicker/releases/download/{tag}/{archive_name}"
            ),
            "size": 123,
        }
    ]
    if with_checksum:
        assets.append(
            {
                "name": f"{archive_name}.sha256",
                "browser_download_url": (
                    "https://github.com/yomihime/CharaPicker/releases/download/"
                    f"{tag}/{archive_name}.sha256"
                ),
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
            _release_payload("v1.1.0-beta", prerelease=True),
            _release_payload("v1.0.3", prerelease=False),
        ]

        release = check_for_update(include_prereleases=False)

        self.assertIsNotNone(release)
        self.assertEqual(release.version.public_tag, "1.0.3")

    @patch("utils.app_update.read_json")
    def test_test_channel_includes_prereleases(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v1.1.0-beta", prerelease=True),
            _release_payload("v1.0.0", prerelease=False),
        ]

        release = check_for_update(include_prereleases=True)

        self.assertIsNotNone(release)
        self.assertEqual(release.version.public_tag, "1.1.0-beta")

    @patch("utils.app_update.read_json")
    def test_newer_release_requires_archive_and_checksum(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v1.1.0-beta", prerelease=True, with_checksum=False)
        ]

        with self.assertRaises(UpdatePackageUnavailableError):
            check_for_update(include_prereleases=True)

    @patch("utils.app_update.read_json")
    def test_current_or_older_release_is_not_an_update(self, read_json) -> None:
        read_json.return_value = [
            _release_payload("v1.0.0-rc", prerelease=True),
            _release_payload("v0.9.0", prerelease=False),
        ]

        self.assertIsNone(check_for_update(include_prereleases=True))

    @patch("utils.app_update.read_json")
    def test_release_assets_must_use_repository_download_origin(self, read_json) -> None:
        payload = _release_payload("v1.1.0", prerelease=False)
        payload["assets"][0]["browser_download_url"] = "https://example.com/update.zip"
        read_json.return_value = [payload]

        with self.assertRaises(UpdatePackageUnavailableError):
            check_for_update(include_prereleases=False)


class UpdateArchiveTests(unittest.TestCase):
    def test_payload_resolver_accepts_official_wrapper_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive_path = root / "update.zip"
            extract_dir = root / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("CharaPicker/CharaPicker.exe", b"new")
                archive.writestr("CharaPicker/CharaPickerUpdater.exe", b"updater")

            _extract_update_archive(archive_path, extract_dir)
            payload_dir = _resolve_update_payload_dir(extract_dir)

            self.assertEqual(payload_dir, (extract_dir / "CharaPicker").resolve())
            self.assertEqual(
                (payload_dir / "CharaPicker.exe").read_bytes(),
                b"new",
            )

    def test_payload_resolver_accepts_flat_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive_path = root / "update.zip"
            extract_dir = root / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("CharaPicker.exe", b"new")
                archive.writestr("CharaPickerUpdater.exe", b"updater")
                archive.writestr("_internal/runtime.dll", b"runtime")

            _extract_update_archive(archive_path, extract_dir)

            self.assertEqual(_resolve_update_payload_dir(extract_dir), extract_dir.resolve())

    def test_payload_resolver_accepts_arbitrary_wrapper_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive_path = root / "update.zip"
            extract_dir = root / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("portable-build/CharaPicker.exe", b"new")
                archive.writestr("portable-build/CharaPickerUpdater.exe", b"updater")

            _extract_update_archive(archive_path, extract_dir)

            self.assertEqual(
                _resolve_update_payload_dir(extract_dir),
                (extract_dir / "portable-build").resolve(),
            )

    def test_payload_resolver_rejects_files_outside_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            extract_dir = root / "extract"
            payload_dir = extract_dir / "portable-build"
            payload_dir.mkdir(parents=True)
            (payload_dir / "CharaPicker.exe").write_bytes(b"new")
            (payload_dir / "CharaPickerUpdater.exe").write_bytes(b"updater")
            (extract_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")

            with self.assertRaises(UpdateDownloadError):
                _resolve_update_payload_dir(extract_dir)

    def test_payload_resolver_rejects_multiple_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            extract_dir = Path(temp_name) / "extract"
            for directory_name in ("first", "second"):
                payload_dir = extract_dir / directory_name
                payload_dir.mkdir(parents=True)
                (payload_dir / "CharaPicker.exe").write_bytes(b"new")
                (payload_dir / "CharaPickerUpdater.exe").write_bytes(b"updater")

            with self.assertRaises(UpdateDownloadError):
                _resolve_update_payload_dir(extract_dir)

    def test_payload_resolver_rejects_nested_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            payload_dir = Path(temp_name) / "extract" / "outer" / "inner"
            payload_dir.mkdir(parents=True)
            (payload_dir / "CharaPicker.exe").write_bytes(b"new")
            (payload_dir / "CharaPickerUpdater.exe").write_bytes(b"updater")

            with self.assertRaises(UpdateDownloadError):
                _resolve_update_payload_dir(Path(temp_name) / "extract")

    def test_payload_resolver_requires_main_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            extract_dir = Path(temp_name) / "extract"
            extract_dir.mkdir()
            (extract_dir / "CharaPickerUpdater.exe").write_bytes(b"updater")

            with self.assertRaises(UpdateDownloadError):
                _resolve_update_payload_dir(extract_dir)

    def test_payload_resolver_requires_update_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            extract_dir = Path(temp_name) / "extract"
            extract_dir.mkdir()
            (extract_dir / "CharaPicker.exe").write_bytes(b"new")

            with self.assertRaises(UpdateDownloadError):
                _resolve_update_payload_dir(extract_dir)

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


class UpdateLaunchTests(unittest.TestCase):
    def test_launch_write_failure_preserves_previous_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            install_dir = root / "install"
            workspace = root / "workspace"
            payload_dir = root / "payload"
            updater_path = payload_dir / "CharaPickerUpdater.exe"
            for directory in (install_dir, workspace, payload_dir):
                directory.mkdir(parents=True)
            updater_path.write_bytes(b"updater")
            request_path = workspace / "update-request.json"
            request_path.write_text("previous request", encoding="utf-8")
            prepared = PreparedUpdate(
                version_tag="1.0.0",
                workspace=workspace,
                payload_dir=payload_dir,
                updater_path=updater_path,
            )

            with (
                patch("utils.app_update.packaged_install_dir", return_value=install_dir),
                patch("utils.atomic_io.os.replace", side_effect=OSError("replace failed")),
            ):
                with self.assertRaises(UpdateLaunchError):
                    launch_prepared_update(
                        prepared,
                        current_pid=1234,
                        failure_title="Update failed",
                        failure_message="Manual recovery required",
                    )

            self.assertEqual(request_path.read_text(encoding="utf-8"), "previous request")
            self.assertEqual(list(workspace.glob(".tmp-*.tmp")), [])

    def test_acknowledgement_write_failure_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            ack_path = Path(temp_name) / "startup-ack"
            ack_path.write_text("previous", encoding="ascii")

            with (
                patch.dict(os.environ, {UPDATE_ACK_ENV: str(ack_path)}),
                patch("utils.atomic_io.os.replace", side_effect=OSError("replace failed")),
            ):
                acknowledge_update_startup()

            self.assertEqual(ack_path.read_text(encoding="ascii"), "previous")
            self.assertEqual(list(ack_path.parent.glob(".tmp-*.tmp")), [])

    def test_launch_request_relaunch_cwd_uses_install_dir_not_current_cwd(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            install_dir = root / "install" / "CharaPicker"
            workspace = root / "workspace"
            payload_dir = root / "payload"
            external_cwd = root / "external-cwd"
            updater_path = payload_dir / "CharaPickerUpdater.exe"
            for directory in (install_dir, workspace, payload_dir, external_cwd):
                directory.mkdir(parents=True)
            updater_path.write_bytes(b"updater")

            prepared = PreparedUpdate(
                version_tag="1.0.0",
                workspace=workspace,
                payload_dir=payload_dir,
                updater_path=updater_path,
            )

            try:
                os.chdir(external_cwd)
                with (
                    patch("utils.app_update.packaged_install_dir", return_value=install_dir),
                    patch("utils.app_update.shutil.copy2"),
                    patch("utils.app_update.subprocess.Popen"),
                ):
                    launch_prepared_update(
                        prepared,
                        current_pid=1234,
                        failure_title="Update failed",
                        failure_message="Manual recovery required",
                    )
            finally:
                os.chdir(original_cwd)

            request = json.loads((workspace / "update-request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["install_dir"], str(install_dir))
            self.assertEqual(request["relaunch_cwd"], str(install_dir))
            self.assertNotEqual(request["relaunch_cwd"], str(external_cwd.resolve()))
            self.assertNotIn("backup_dir", request)
            self.assertNotIn("preserve", request)


if __name__ == "__main__":
    unittest.main()
