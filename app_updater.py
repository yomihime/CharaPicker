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
ALLOWED_PRESERVED_PATHS = {"projects", "config.yaml", "log", "bin", "models"}


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
    current_pid = _required_positive_int(request, "current_pid")
    install_dir = _required_path(request, "install_dir")
    payload_dir = _required_path(request, "payload_dir")
    workspace = _required_path(request, "workspace")
    backup_dir = _required_path(request, "backup_dir")
    ack_path = _required_path(request, "ack_path")
    relaunch_cwd = _required_path(request, "relaunch_cwd")
    executable_name = str(request.get("executable_name") or "").strip()
    preserve = _preserved_paths(request.get("preserve"))

    _validate_layout(
        request_path=request_path,
        install_dir=install_dir,
        payload_dir=payload_dir,
        workspace=workspace,
        backup_dir=backup_dir,
        relaunch_cwd=relaunch_cwd,
        executable_name=executable_name,
    )
    _write_log(log_path, f"Waiting for process {current_pid}")
    if not _wait_for_process_exit(current_pid, WAIT_TIMEOUT_SECONDS):
        raise UpdaterError("The running application did not exit in time.")

    installed_new_version = False
    new_process: subprocess.Popen[bytes] | None = None
    try:
        install_dir.rename(backup_dir)
        _write_log(log_path, f"Backed up installation to {backup_dir}")
        payload_dir.rename(install_dir)
        installed_new_version = True
        _move_preserved_paths(backup_dir, install_dir, preserve)

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
        _write_log(log_path, "Rolling back update")
        _stop_process(new_process)
        _rollback(
            install_dir=install_dir,
            backup_dir=backup_dir,
            workspace=workspace,
            preserve=preserve,
            installed_new_version=installed_new_version,
            executable_name=executable_name,
            relaunch_cwd=relaunch_cwd,
        )
        raise

    shutil.rmtree(backup_dir, ignore_errors=True)
    _write_log(log_path, "Update completed successfully")
    shutil.rmtree(workspace, ignore_errors=True)


def _validate_layout(
    *,
    request_path: Path,
    install_dir: Path,
    payload_dir: Path,
    workspace: Path,
    backup_dir: Path,
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
    if install_dir.parent != workspace.parent or install_dir.parent != backup_dir.parent:
        raise UpdaterError("Update paths must share the installation parent directory.")
    if not relaunch_cwd.is_dir():
        raise UpdaterError("The application working directory is invalid.")
    if backup_dir.exists():
        raise UpdaterError("The update backup directory already exists.")


def _rollback(
    *,
    install_dir: Path,
    backup_dir: Path,
    workspace: Path,
    preserve: tuple[str, ...],
    installed_new_version: bool,
    executable_name: str,
    relaunch_cwd: Path,
) -> None:
    try:
        if installed_new_version and install_dir.exists():
            _move_preserved_paths(install_dir, backup_dir, preserve)
            failed_dir = workspace / "failed-installation"
            if failed_dir.exists():
                shutil.rmtree(failed_dir, ignore_errors=True)
            install_dir.rename(failed_dir)
        if backup_dir.exists() and not install_dir.exists():
            backup_dir.rename(install_dir)
        old_executable = install_dir / executable_name
        if old_executable.is_file():
            subprocess.Popen([str(old_executable)], cwd=relaunch_cwd, close_fds=True)
        shutil.rmtree(workspace, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        raise UpdaterError(f"Automatic rollback failed: {exc}") from exc


def _move_preserved_paths(source_root: Path, target_root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        source = source_root / name
        if not source.exists():
            continue
        target = target_root / name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(source), str(target))


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


def _preserved_paths(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise UpdaterError("Invalid preserved path list.")
    names: list[str] = []
    for item in value:
        name = str(item).strip()
        path = Path(name)
        if not name or path.is_absolute() or len(path.parts) != 1 or name in {".", ".."}:
            raise UpdaterError("Invalid preserved path.")
        if name not in ALLOWED_PRESERVED_PATHS:
            raise UpdaterError("Unsupported preserved path.")
        names.append(name)
    return tuple(names)


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
