from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from utils.paths import APP_ROOT


LOGGER = logging.getLogger(__name__)

BIN_ROOT = APP_ROOT / "bin"
MODELS_ROOT = APP_ROOT / "models"

FFMPEG_DIRECTORY_NAME = "ffmpeg"
LLAMACPP_DIRECTORY_NAME = "llama.cpp"
WHISPERCPP_DIRECTORY_NAME = "whisper.cpp"

FFMPEG_ROOT = BIN_ROOT / FFMPEG_DIRECTORY_NAME
LLAMACPP_ROOT = BIN_ROOT / LLAMACPP_DIRECTORY_NAME
WHISPERCPP_ROOT = BIN_ROOT / WHISPERCPP_DIRECTORY_NAME
WHISPER_MODEL_ROOT = MODELS_ROOT / "whisper"


def managed_runtime_root(bin_root: Path, directory_name: str) -> Path:
    return bin_root / directory_name


def managed_runtime_install_dir(
    bin_root: Path,
    directory_name: str,
    version: str,
    package_id: str,
) -> Path:
    return (
        managed_runtime_root(bin_root, directory_name)
        / safe_runtime_segment(version)
        / safe_runtime_segment(package_id)
    )


def iter_runtime_binary_candidates(
    bin_root: Path,
    directory_name: str,
    file_names: Iterable[str],
    *,
    legacy_directory_prefixes: Iterable[str] = (),
) -> Iterable[Path]:
    """Yield managed candidates first, followed by narrowly scoped legacy locations."""

    names = tuple(file_names)
    managed_root = managed_runtime_root(bin_root, directory_name)
    yield from _iter_candidates_under(managed_root, names)

    for file_name in names:
        candidate = bin_root / file_name
        if _path_is_file(candidate):
            yield candidate

    prefixes = tuple(prefix.casefold() for prefix in legacy_directory_prefixes)
    if not prefixes:
        return
    try:
        children = sorted(bin_root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        LOGGER.warning("Runtime directory scan failed; root=%s error=%s", bin_root, exc)
        return
    for child in children:
        if child == managed_root or not _path_is_dir(child):
            continue
        if child.name.casefold().startswith(prefixes):
            yield from _iter_candidates_under(child, names)


def safe_runtime_segment(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in value
    )
    return cleaned.strip(".-") or "unknown"


def replace_runtime_directory(source_dir: Path, target_dir: Path) -> None:
    """Replace one managed runtime package while retaining a rollback copy on failure."""

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = target_dir.with_name(f"{target_dir.name}.backup")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if target_dir.exists():
        target_dir.replace(backup_dir)
    try:
        source_dir.replace(target_dir)
    except OSError:
        if backup_dir.exists() and not target_dir.exists():
            backup_dir.replace(target_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)


def _iter_candidates_under(root: Path, file_names: tuple[str, ...]) -> Iterable[Path]:
    if not _path_exists(root):
        return
    for file_name in file_names:
        candidate = root / file_name
        if _path_is_file(candidate):
            yield candidate
    for file_name in file_names:
        try:
            candidates = sorted(
                root.rglob(file_name),
                key=_natural_path_key,
                reverse=True,
            )
        except OSError as exc:
            LOGGER.warning(
                "Runtime binary scan failed; root=%s pattern=%s error=%s",
                root,
                file_name,
                exc,
            )
            continue
        for candidate in candidates:
            if candidate.parent == root:
                continue
            if _path_is_file(candidate):
                yield candidate


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError as exc:
        LOGGER.warning("Runtime path probe failed; path=%s error=%s", path, exc)
        return False


def _path_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError as exc:
        LOGGER.warning("Runtime file probe failed; path=%s error=%s", path, exc)
        return False


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError as exc:
        LOGGER.warning("Runtime directory probe failed; path=%s error=%s", path, exc)
        return False


def _natural_path_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    parts = re.split(r"(\d+)", path.as_posix().casefold())
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in parts
    )
