from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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
