from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from collections.abc import Callable

from utils.paths import ensure_project_tree, project_paths

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int, str], None]
CancelledCallback = Callable[[], bool]
COPY_BUFFER_SIZE = 1024 * 1024 * 8

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


def import_sources_to_raw(
    project_id: str,
    source_paths: list[str],
    progress: ProgressCallback | None = None,
    cancelled: CancelledCallback | None = None,
) -> list[Path]:
    raw_root = ensure_project_tree(project_id).raw
    imported_paths: list[Path] = []
    existing_targets = set(_iter_existing_sources(raw_root))
    external_sources = _expand_source_paths(source_paths)
    total = len(external_sources)
    if progress is not None:
        progress(0, total, "")
    for index, source in enumerate(external_sources, start=1):
        if cancelled is not None and cancelled():
            raise RuntimeError("Source processing cancelled")
        target = raw_root / source.relative_target
        if _copy_source_file(source.path, target, cancelled=cancelled):
            imported_paths.append(target)
        elif target.exists() and target in existing_targets:
            imported_paths.append(target)
        if progress is not None:
            progress(index, total, source.relative_target.as_posix())
    LOGGER.info("Sources imported to raw; project_id=%s count=%s", project_id, len(imported_paths))
    return imported_paths


def source_raw_targets(project_id: str, source_paths: list[str]) -> list[Path]:
    return [raw_target for _, raw_target in source_raw_target_pairs(project_id, source_paths)]


def source_raw_target_pairs(project_id: str, source_paths: list[str]) -> list[tuple[Path, Path]]:
    raw_root = project_paths(project_id).raw
    return [(source.path, raw_root / source.relative_target) for source in _expand_source_paths(source_paths)]


def remove_project_sources(project_id: str, source_paths: list[str]) -> int:
    paths = project_paths(project_id)
    removed_count = 0
    for raw_target in source_raw_targets(project_id, source_paths):
        if _remove_path(raw_target):
            removed_count += 1
        material_target = _material_target_for_raw(paths.raw, paths.materials, raw_target)
        _remove_path(material_target)
        _remove_empty_parents(raw_target.parent, paths.raw)
        _remove_empty_parents(material_target.parent, paths.materials)
    LOGGER.info("Project sources removed; project_id=%s count=%s", project_id, removed_count)
    return removed_count


def remove_raw_sources(project_id: str, raw_sources: list[Path]) -> int:
    paths = project_paths(project_id)
    removed_count = 0
    for raw_source in raw_sources:
        try:
            raw_target = raw_source.resolve().relative_to(paths.raw.resolve())
        except ValueError:
            LOGGER.warning("Raw source removal skipped because it is outside raw; path=%s", raw_source)
            continue
        raw_path = paths.raw / raw_target
        material_path = paths.materials / raw_target
        if _remove_path(raw_path):
            removed_count += 1
        _remove_path(material_path)
        _remove_empty_parents(raw_path.parent, paths.raw)
        _remove_empty_parents(material_path.parent, paths.materials)
    LOGGER.info("Raw sources removed; project_id=%s count=%s", project_id, removed_count)
    return removed_count


def clean_raw_sources(project_id: str, raw_sources: list[Path]) -> list[str]:
    paths = project_paths(project_id)
    cleaned_paths: list[str] = []
    for raw_source in raw_sources:
        try:
            relative_path = raw_source.resolve().relative_to(paths.raw.resolve())
        except ValueError:
            LOGGER.warning("Raw cleanup skipped because it is outside raw; path=%s", raw_source)
            continue

        material_path = paths.materials / relative_path
        if not raw_source.exists():
            continue
        if not _materialize_source(raw_source, material_path):
            continue
        if _remove_path(raw_source):
            cleaned_paths.append(relative_path.as_posix())
            _remove_empty_parents(raw_source.parent, paths.raw)
    LOGGER.info("Raw sources cleaned; project_id=%s count=%s", project_id, len(cleaned_paths))
    return cleaned_paths


def import_original_sources(project_id: str, source_paths: list[str]) -> int:
    return len(import_sources_to_raw(project_id, source_paths))


def link_raw_sources_to_materials(
    project_id: str,
    raw_sources: list[Path] | None = None,
    progress: ProgressCallback | None = None,
) -> int:
    paths = ensure_project_tree(project_id)
    raw_root = paths.raw
    materials_root = paths.materials
    sources = raw_sources or _iter_existing_sources(raw_root)
    total = len(sources)
    if progress is not None:
        progress(0, total, "")
    linked_count = 0
    for index, source in enumerate(sources, start=1):
        try:
            relative_path = source.resolve().relative_to(raw_root.resolve())
        except ValueError:
            LOGGER.warning("Raw source link skipped because it is outside raw; path=%s", source)
            continue
        target = materials_root / relative_path
        if _ensure_symlink(source, target):
            linked_count += 1
        if progress is not None:
            progress(index, total, relative_path.as_posix())
    LOGGER.info("Raw sources linked to materials; project_id=%s count=%s", project_id, linked_count)
    return linked_count


class SourceImportTarget:
    def __init__(self, path: Path, relative_target: Path) -> None:
        self.path = path
        self.relative_target = relative_target


def _expand_source_paths(source_paths: list[str]) -> list[SourceImportTarget]:
    sources: list[SourceImportTarget] = []
    for source_path in source_paths:
        source = Path(source_path).expanduser()
        if not source.exists():
            LOGGER.warning("Source import skipped because path does not exist; path=%s", source)
            continue
        if source.is_file() and _is_supported_source(source):
            sources.append(SourceImportTarget(source, Path(source.name)))
            continue
        if source.is_dir():
            sources.extend(
                SourceImportTarget(path, Path(source.name) / path.relative_to(source))
                for path in _iter_directory_sources(source)
            )
    return sources


def _iter_existing_sources(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        [
            path
            for path in root.rglob("*")
            if path.is_file() and (not path.suffix or path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES)
        ],
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )


def _legacy_import_original_sources(project_id: str, source_paths: list[str]) -> int:
    raw_root = project_paths(project_id).raw
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


def _copy_source_file(source: Path, target: Path, cancelled: CancelledCallback | None = None) -> bool:
    if not _is_supported_source(source):
        return False
    try:
        if source.resolve() == target.resolve():
            return False
    except OSError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_interruptible(source, target, cancelled=cancelled)
    return True


def _copy_file_interruptible(source: Path, target: Path, cancelled: CancelledCallback | None = None) -> None:
    with source.open("rb") as source_file, target.open("wb") as target_file:
        while True:
            if cancelled is not None and cancelled():
                target_file.close()
                target.unlink(missing_ok=True)
                raise RuntimeError("Source processing cancelled")
            chunk = source_file.read(COPY_BUFFER_SIZE)
            if not chunk:
                break
            target_file.write(chunk)
    shutil.copystat(source, target)


def _ensure_symlink(source: Path, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if target.is_symlink() and target.resolve() == source.resolve():
            return True
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink(source, target)
    except OSError:
        LOGGER.warning("Source symlink failed; falling back to hard link; source=%s target=%s", source, target)
        try:
            os.link(source, target)
        except OSError:
            LOGGER.warning("Source lightweight link failed; source=%s target=%s", source, target, exc_info=True)
            return False
    return True


def _materialize_source(source: Path, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if target.is_symlink():
            temp_target = target.with_name(f"{target.name}.materializing")
            if temp_target.exists() or temp_target.is_symlink():
                temp_target.unlink()
            shutil.copy2(source, temp_target)
            target.unlink()
            temp_target.replace(target)
            return True
        if target.exists():
            return True
        shutil.copy2(source, target)
    except OSError:
        LOGGER.warning("Source materialize failed; source=%s target=%s", source, target, exc_info=True)
        return False
    return True


def _material_target_for_raw(raw_root: Path, materials_root: Path, raw_source: Path) -> Path:
    try:
        relative_path = raw_source.resolve().relative_to(raw_root.resolve())
    except ValueError:
        return materials_root / raw_source.name
    return materials_root / relative_path


def _remove_path(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return True
        if path.is_dir():
            shutil.rmtree(path)
            return True
    except OSError:
        LOGGER.warning("Source path removal failed; path=%s", path, exc_info=True)
    return False


def _remove_empty_parents(start: Path, stop: Path) -> None:
    try:
        stop_resolved = stop.resolve()
    except OSError:
        return
    current = start
    while current != stop:
        try:
            if current.resolve() == stop_resolved or stop_resolved not in current.resolve().parents:
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _is_supported_source(path: Path) -> bool:
    return not path.suffix or path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
