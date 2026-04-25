from __future__ import annotations

import subprocess
from pathlib import Path

from utils.paths import APP_ROOT

CONDA_ENV_NAME = "CharaPicker"
BIN_ROOT = APP_ROOT / "bin"
LLAMACPP_CANDIDATES = (
    "llama-cli.exe",
    "llama-cli",
    "llama-server.exe",
    "llama-server",
    "llama.exe",
    "llama",
    "main.exe",
    "main",
)
LLAMACPP_CHECK_TIMEOUT_SECONDS = 6
FFMPEG_CANDIDATES = ("ffmpeg.exe", "ffmpeg")
FFMPEG_CHECK_TIMEOUT_SECONDS = 6


def conda_run_prefix() -> list[str]:
    return ["conda", "run", "-n", CONDA_ENV_NAME]


def find_llamacpp_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in LLAMACPP_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file():
            return candidate
    for file_name in LLAMACPP_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file():
                return candidate
    return None


def is_llamacpp_binary_usable(binary_path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(binary_path), "--help"],
            cwd=binary_path.parent,
            capture_output=True,
            timeout=LLAMACPP_CHECK_TIMEOUT_SECONDS,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def find_usable_llamacpp_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in LLAMACPP_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file() and is_llamacpp_binary_usable(candidate):
            return candidate
    for file_name in LLAMACPP_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file() and is_llamacpp_binary_usable(candidate):
                return candidate
    return None


def has_llamacpp_binary(bin_root: Path = BIN_ROOT) -> bool:
    return find_usable_llamacpp_binary(bin_root) is not None


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
