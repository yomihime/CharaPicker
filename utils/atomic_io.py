from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


TextValidator = Callable[[str], object]


class DataCorruptionError(ValueError):
    def __init__(self, path: Path, backup_path: Path, *, backup_available: bool) -> None:
        self.path = Path(path)
        self.backup_path = Path(backup_path)
        self.backup_available = backup_available
        backup_status = (
            f" A valid backup is available at: {self.backup_path}"
            if backup_available
            else " No valid backup is available."
        )
        super().__init__(f"Stored data is invalid: {self.path}.{backup_status}")


def backup_path_for(path: Path) -> Path:
    path = Path(path)
    return path.with_name(f"{path.name}.bak")


def write_text_atomically(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def write_json_atomically(
    path: Path,
    payload: Any,
    *,
    trailing_newline: bool = True,
) -> Path:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if trailing_newline:
        text += "\n"
    return write_text_atomically(path, text)


def read_validated_text(
    path: Path,
    validator: TextValidator,
    *,
    encoding: str = "utf-8",
) -> str:
    path = Path(path)
    try:
        text = path.read_text(encoding=encoding)
    except UnicodeError:
        raise _corruption_error(path, validator, encoding=encoding) from None
    if not _is_valid_text(text, validator):
        raise _corruption_error(path, validator, encoding=encoding)
    return text


def write_text_atomically_with_backup(
    path: Path,
    text: str,
    validator: TextValidator,
    *,
    encoding: str = "utf-8",
) -> Path:
    path = Path(path)
    if not _is_valid_text(text, validator):
        raise ValueError(f"refusing to write invalid data: {path}")
    if path.exists():
        existing = read_validated_text(path, validator, encoding=encoding)
        write_text_atomically(backup_path_for(path), existing, encoding=encoding)
    return write_text_atomically(path, text, encoding=encoding)


def restore_backup_atomically(
    path: Path,
    validator: TextValidator,
    *,
    encoding: str = "utf-8",
) -> Path:
    path = Path(path)
    backup_path = backup_path_for(path)
    try:
        backup_text = backup_path.read_text(encoding=encoding)
    except (OSError, UnicodeError):
        raise DataCorruptionError(path, backup_path, backup_available=False) from None
    if not _is_valid_text(backup_text, validator):
        raise DataCorruptionError(path, backup_path, backup_available=False)
    return write_text_atomically(path, backup_text, encoding=encoding)


def _corruption_error(
    path: Path,
    validator: TextValidator,
    *,
    encoding: str,
) -> DataCorruptionError:
    backup_path = backup_path_for(path)
    try:
        backup_text = backup_path.read_text(encoding=encoding)
    except (OSError, UnicodeError):
        backup_available = False
    else:
        backup_available = _is_valid_text(backup_text, validator)
    return DataCorruptionError(path, backup_path, backup_available=backup_available)


def _is_valid_text(text: str, validator: TextValidator) -> bool:
    try:
        result = validator(text)
    except Exception:  # noqa: BLE001
        return False
    return result is not False


def _sync_directory(path: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not directory_flag:
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | directory_flag)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
