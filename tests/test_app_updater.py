from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app_updater import UpdaterError, _apply_update


class AppUpdaterTests(unittest.TestCase):
    def _update_fixture(self, root: Path) -> tuple[dict[str, object], Path]:
        install_dir = root / "CharaPicker"
        install_dir.mkdir()
        (install_dir / "CharaPicker.exe").write_bytes(b"old")
        (install_dir / "config.yaml").write_text("version: 1\n", encoding="utf-8")
        projects_dir = install_dir / "projects"
        projects_dir.mkdir()
        (projects_dir / "kept.txt").write_text("user-data", encoding="utf-8")

        workspace = root / ".charapicker-update-test"
        payload_dir = workspace / "payload" / "CharaPicker"
        payload_dir.mkdir(parents=True)
        (payload_dir / "CharaPicker.exe").write_bytes(b"new")
        (payload_dir / "CharaPickerUpdater.exe").write_bytes(b"updater")

        request_path = workspace / "update-request.json"
        request: dict[str, object] = {
            "schema_version": 1,
            "current_pid": 42,
            "install_dir": str(install_dir),
            "payload_dir": str(payload_dir),
            "workspace": str(workspace),
            "backup_dir": str(root / ".charapicker-backup-test"),
            "ack_path": str(workspace / "startup-ack"),
            "log_path": str(root / "updater.log"),
            "executable_name": "CharaPicker.exe",
            "relaunch_cwd": str(install_dir),
            "preserve": ["projects", "config.yaml", "log", "bin", "models"],
            "failure_title": "failure",
            "failure_message": "failed",
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request, request_path

    @patch("app_updater._wait_for_process_exit", return_value=True)
    @patch("app_updater._wait_for_startup_ack", return_value=True)
    @patch("app_updater.subprocess.Popen")
    def test_update_replaces_program_and_preserves_user_data(
        self,
        popen,
        _wait_for_ack,
        _wait_for_exit,
    ) -> None:
        process = Mock()
        process.pid = 99
        process.poll.return_value = None
        popen.return_value = process

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            request, request_path = self._update_fixture(root)

            _apply_update(request, request_path, root / "updater.log")

            install_dir = root / "CharaPicker"
            self.assertEqual((install_dir / "CharaPicker.exe").read_bytes(), b"new")
            self.assertEqual(
                (install_dir / "projects" / "kept.txt").read_text(encoding="utf-8"),
                "user-data",
            )
            self.assertTrue((install_dir / "config.yaml").is_file())
            self.assertFalse((root / ".charapicker-update-test").exists())
            self.assertFalse((root / ".charapicker-backup-test").exists())

    @patch("app_updater._wait_for_process_exit", return_value=True)
    @patch("app_updater._wait_for_startup_ack", return_value=False)
    @patch("app_updater.subprocess.Popen")
    def test_failed_new_version_rolls_back_old_program_and_user_data(
        self,
        popen,
        _wait_for_ack,
        _wait_for_exit,
    ) -> None:
        process = Mock()
        process.pid = 99
        process.poll.return_value = 1
        popen.return_value = process

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            request, request_path = self._update_fixture(root)

            with self.assertRaises(UpdaterError):
                _apply_update(request, request_path, root / "updater.log")

            install_dir = root / "CharaPicker"
            self.assertEqual((install_dir / "CharaPicker.exe").read_bytes(), b"old")
            self.assertEqual(
                (install_dir / "projects" / "kept.txt").read_text(encoding="utf-8"),
                "user-data",
            )
            self.assertTrue((install_dir / "config.yaml").is_file())
            self.assertFalse((root / ".charapicker-update-test").exists())


if __name__ == "__main__":
    unittest.main()
