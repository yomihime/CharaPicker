from __future__ import annotations

import logging
import shutil
from pathlib import Path

from utils.paths import ensure_project_tree

LOGGER = logging.getLogger(__name__)

SUPPORTED_SOURCE_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".flv",
    ".wmv",
    ".m4v",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".txt",
    ".md",
    ".json",
}


def import_original_sources(project_id: str, source_paths: list[str]) -> int:
    raw_root = ensure_project_tree(project_id).raw
    imported_count = 0
    for source_path in source_paths:
        source = Path(source_path).expanduser()
        if not source.exists():
            LOGGER.warning("Source import skipped because path does not exist; path=%s", source)
            continue
        if source.is_file():
            if _copy_source_file(source, raw_root / source.name):
                imported_count += 1
            continue
        if source.is_dir():
            imported_count += _copy_source_directory(source, raw_root / source.name)
    LOGGER.info("Original sources imported; project_id=%s count=%s", project_id, imported_count)
    return imported_count


def _copy_source_directory(source_root: Path, target_root: Path) -> int:
    imported_count = 0
    for source in _iter_directory_sources(source_root):
        relative_path = source.relative_to(source_root)
        if _copy_source_file(source, target_root / relative_path):
            imported_count += 1
    return imported_count


def _iter_directory_sources(source_root: Path) -> list[Path]:
    sources: list[Path] = []
    for path in source_root.iterdir():
        if path.is_file() and _is_supported_source(path):
            sources.append(path)
            continue
        if path.is_dir():
            for child in path.iterdir():
                if child.is_file() and _is_supported_source(child):
                    sources.append(child)
    return sorted(sources, key=lambda path: path.relative_to(source_root).as_posix().lower())


def _copy_source_file(source: Path, target: Path) -> bool:
    if not _is_supported_source(source):
        return False
    try:
        if source.resolve() == target.resolve():
            return False
    except OSError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _is_supported_source(path: Path) -> bool:
    return not path.suffix or path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
