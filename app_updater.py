from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


WAIT_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 0.25
UPDATE_ACK_ENV = "CHARAPICKER_UPDATE_ACK_PATH"
UPDATE_BACKUP_DIR_NAME = "update_backup"
UPDATE_DOWNLOAD_DIR_NAME = "download"
PROTECTED_RUNTIME_NAMES = {
    "projects",
    "config.yaml",
    "log",
    "bin",
    "models",
    UPDATE_BACKUP_DIR_NAME,
    UPDATE_DOWNLOAD_DIR_NAME,
}


class UpdaterError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args(argv)

    request_path = Path(args.request).resolve()
    request: dict[str, Any] = {}
    log_path = Path(tempfile.gettempdir()) / "CharaPickerUpdater.log"
    exit_code = 0
    try:
        request = _load_request(request_path)
        log_path = _required_path(request, "log_path")
        _apply_update(request, request_path, log_path)
    except Exception as exc:  # noqa: BLE001
        _write_log(log_path, f"Update failed: {exc!r}")
        _show_error(
            str(request.get("failure_title") or "CharaPicker Update"),
            f"{request.get('failure_message') or 'The update failed.'}\n\n{exc}",
        )
        exit_code = 1
    finally:
        _schedule_self_delete()
    return exit_code


def _load_request(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdaterError(f"Cannot read update request: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise UpdaterError("Unsupported update request.")
    return payload


def _apply_update(request: dict[str, Any], request_path: Path, log_path: Path) -> None:
    request_path = request_path.resolve()
    current_pid = _required_positive_int(request, "current_pid")
    install_dir = _required_path(request, "install_dir")
    payload_dir = _required_path(request, "payload_dir")
    workspace = _required_path(request, "workspace")
    ack_path = _required_path(request, "ack_path")
    relaunch_cwd = _required_path(request, "relaunch_cwd")
    executable_name = str(request.get("executable_name") or "").strip()

    _validate_layout(
        request_path=request_path,
        install_dir=install_dir,
        payload_dir=payload_dir,
        workspace=workspace,
        relaunch_cwd=relaunch_cwd,
        executable_name=executable_name,
    )
    _write_log(log_path, f"Waiting for process {current_pid}")
    if not _wait_for_process_exit(current_pid, WAIT_TIMEOUT_SECONDS):
        raise UpdaterError("The running application did not exit in time.")

    new_process: subprocess.Popen[bytes] | None = None
    try:
        download_dir = install_dir / UPDATE_DOWNLOAD_DIR_NAME
        backup_dir = install_dir / UPDATE_BACKUP_DIR_NAME
        _retain_update_downloads(workspace, download_dir)
        _write_log(log_path, f"Retained verified update artifacts in {download_dir}")
        _backup_replaced_paths(payload_dir, install_dir, backup_dir)
        _write_log(log_path, f"Backed up replaced program paths to {backup_dir}")
        _write_log(log_path, f"Overlaying update payload into {install_dir}")
        shutil.copytree(payload_dir, install_dir, dirs_exist_ok=True)
        _write_log(log_path, "Update payload copied into installation directory")

        executable = install_dir / executable_name
        if not executable.is_file():
            raise UpdaterError(f"Updated executable is missing: {executable_name}")
        environment = os.environ.copy()
        environment[UPDATE_ACK_ENV] = str(ack_path)
        new_process = subprocess.Popen(
            [str(executable)],
            cwd=relaunch_cwd,
            env=environment,
            close_fds=True,
        )
        _write_log(log_path, f"Started updated application with pid {new_process.pid}")
        if not _wait_for_startup_ack(new_process, ack_path, WAIT_TIMEOUT_SECONDS):
            raise UpdaterError("The updated application did not start successfully.")
    except Exception:
        _write_log(log_path, "Update failed; automatic rollback is not available")
        _stop_process(new_process)
        raise

    _write_log(log_path, "Update completed successfully")
    shutil.rmtree(workspace, ignore_errors=True)


def _validate_layout(
    *,
    request_path: Path,
    install_dir: Path,
    payload_dir: Path,
    workspace: Path,
    relaunch_cwd: Path,
    executable_name: str,
) -> None:
    if not executable_name or Path(executable_name).name != executable_name:
        raise UpdaterError("Invalid executable name.")
    if not install_dir.is_dir() or not (install_dir / executable_name).is_file():
        raise UpdaterError("The current installation directory is invalid.")
    if not workspace.is_dir() or not request_path.is_relative_to(workspace):
        raise UpdaterError("The update workspace is invalid.")
    if not payload_dir.is_dir() or not payload_dir.is_relative_to(workspace):
        raise UpdaterError("The update payload directory is invalid.")
    if not (payload_dir / executable_name).is_file():
        raise UpdaterError("The update payload is incomplete.")
    payload_names = {item.name.casefold(): item.name for item in payload_dir.iterdir()}
    protected_payload_names = {
        payload_names[name.casefold()]
        for name in PROTECTED_RUNTIME_NAMES
        if name.casefold() in payload_names
    }
    if protected_payload_names:
        names = ", ".join(sorted(protected_payload_names))
        raise UpdaterError(f"The update payload contains protected runtime data: {names}")
    if install_dir.parent != workspace.parent:
        raise UpdaterError("The update workspace must share the installation parent directory.")
    if relaunch_cwd != install_dir or not relaunch_cwd.is_dir():
        raise UpdaterError("The application working directory is invalid.")


def _retain_update_downloads(workspace: Path, download_dir: Path) -> None:
    artifacts = sorted(
        path
        for path in workspace.iterdir()
        if path.is_file()
        and (
            path.suffix.lower() == ".zip"
            or path.name.lower().endswith(".zip.sha256")
        )
    )
    if not artifacts:
        return
    download_dir.mkdir(parents=True, exist_ok=True)
    for source in artifacts:
        shutil.copy2(source, download_dir / source.name)


def _backup_replaced_paths(payload_dir: Path, install_dir: Path, backup_dir: Path) -> None:
    if backup_dir.exists():
        if backup_dir.is_dir():
            shutil.rmtree(backup_dir)
        else:
            backup_dir.unlink()
    backup_dir.mkdir(parents=True)
    for payload_item in sorted(payload_dir.iterdir(), key=lambda path: path.name.casefold()):
        installed_item = install_dir / payload_item.name
        if not installed_item.exists():
            continue
        backup_item = backup_dir / payload_item.name
        if installed_item.is_dir():
            shutil.copytree(installed_item, backup_item)
        else:
            shutil.copy2(installed_item, backup_item)


def _wait_for_process_exit(pid: int, timeout: float) -> bool:
    if sys.platform != "win32":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(POLL_INTERVAL_SECONDS)
        return False

    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == wait_object_0:
            return True
        if result == wait_timeout:
            return False
        raise UpdaterError(f"Failed while waiting for application process: {result}")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _wait_for_startup_ack(
    process: subprocess.Popen[bytes],
    ack_path: Path,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ack_path.is_file():
            return True
        if process.poll() is not None:
            return False
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def _required_positive_int(payload: dict[str, Any], key: str) -> int:
    try:
        value = int(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdaterError(f"Invalid {key}.") from exc
    if value <= 0:
        raise UpdaterError(f"Invalid {key}.")
    return value


def _required_path(payload: dict[str, Any], key: str) -> Path:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise UpdaterError(f"Missing {key}.")
    return Path(value).resolve()


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=10)
        except Exception:
            pass


def _write_log(path: Path, message: str) -> None:
    try:
        with path.open("a", encoding="utf-8") as output:
            output.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _show_error(title: str, message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def _schedule_self_delete() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    move_file_delay_until_reboot = 0x4
    try:
        ctypes.windll.kernel32.MoveFileExW(
            str(Path(sys.executable).resolve()),
            None,
            move_file_delay_until_reboot,
        )
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
