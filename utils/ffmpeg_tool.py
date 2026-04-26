from __future__ import annotations

import subprocess
from pathlib import Path

from utils.env_manager import BIN_ROOT

FFMPEG_CANDIDATES = ("ffmpeg.exe", "ffmpeg")
FFMPEG_CHECK_TIMEOUT_SECONDS = 6


def find_ffmpeg_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in FFMPEG_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file():
            return candidate
    for file_name in FFMPEG_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file():
                return candidate
    return None


def is_ffmpeg_binary_usable(binary_path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(binary_path), "-version"],
            cwd=binary_path.parent,
            capture_output=True,
            timeout=FFMPEG_CHECK_TIMEOUT_SECONDS,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and "ffmpeg" in completed.stdout.lower()


def find_usable_ffmpeg_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in FFMPEG_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file() and is_ffmpeg_binary_usable(candidate):
            return candidate
    for file_name in FFMPEG_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file() and is_ffmpeg_binary_usable(candidate):
                return candidate
    return None


def has_ffmpeg_binary(bin_root: Path = BIN_ROOT) -> bool:
    return find_usable_ffmpeg_binary(bin_root) is not None
