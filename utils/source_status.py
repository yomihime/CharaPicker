from __future__ import annotations

from pathlib import Path

from core.models import ProjectConfig
from utils.paths import project_paths
from utils.source_importer import (
    SUPPORTED_SOURCE_SUFFIXES,
    source_raw_target_pairs,
    source_raw_targets,
)


SOURCE_KIND_EXTERNAL = "external"
SOURCE_KIND_PROJECT = "project"
SOURCE_STATUS_NEW = "new"
SOURCE_STATUS_PROCESSED = "processed"
SOURCE_STATUS_STALE = "stale"
SOURCE_STATUS_RAW_CLEANED = "rawCleaned"


def source_display_text(project_id: str, source_path: str, source_kind: str) -> str:
    if source_kind != SOURCE_KIND_PROJECT:
        return source_path

    raw_root = project_paths(project_id).raw
    try:
        return Path(source_path).resolve().relative_to(raw_root.resolve()).as_posix()
    except ValueError:
        return source_path


def source_status(config: ProjectConfig, source_path: str, source_kind: str) -> str:
    paths = project_paths(config.project_id)
    if source_kind == SOURCE_KIND_PROJECT:
        raw_source = Path(source_path)
        material_target = material_target_for_raw(paths.raw, paths.materials, raw_source)
        return (
            SOURCE_STATUS_PROCESSED
            if material_target.exists() or material_target.is_symlink()
            else SOURCE_STATUS_STALE
        )

    source = Path(source_path).expanduser()
    raw_pairs = source_raw_target_pairs(config.project_id, [source_path])
    raw_targets = [raw_target for _, raw_target in raw_pairs]
    cleaned_paths = set(config.raw_cleaned_paths)
    if not raw_targets:
        return SOURCE_STATUS_NEW
    if all(raw_relative_path(paths.raw, raw_target) in cleaned_paths for raw_target in raw_targets):
        material_targets = [
            material_target_for_raw(paths.raw, paths.materials, raw_target)
            for raw_target in raw_targets
        ]
        if material_targets and all(material_target.exists() for material_target in material_targets):
            return SOURCE_STATUS_RAW_CLEANED
    existing_raw_targets = [raw_target for raw_target in raw_targets if raw_target.exists()]
    if not existing_raw_targets:
        return SOURCE_STATUS_NEW
    if len(existing_raw_targets) != len(raw_targets):
        return SOURCE_STATUS_STALE
    if external_source_is_newer(source, raw_pairs):
        return SOURCE_STATUS_STALE
    material_targets = [
        material_target_for_raw(paths.raw, paths.materials, raw_target)
        for raw_target in existing_raw_targets
    ]
    if material_targets and all(
        material_target.exists() or material_target.is_symlink()
        for material_target in material_targets
    ):
        return SOURCE_STATUS_PROCESSED
    return SOURCE_STATUS_STALE


def project_source_paths(project_id: str) -> list[Path]:
    raw_root = project_paths(project_id).raw
    if not raw_root.exists():
        return []
    paths = [
        path
        for path in raw_root.rglob("*")
        if path.is_file() and (not path.suffix or path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES)
    ]
    return sorted(paths, key=lambda path: path.relative_to(raw_root).as_posix().lower())


def shadowed_raw_paths(project_id: str, external_paths: list[str]) -> set[Path]:
    return {path.resolve() for path in source_raw_targets(project_id, external_paths)}


def selected_raw_sources_for_item(project_id: str, source_path: str, source_kind: str) -> list[Path]:
    if source_kind == SOURCE_KIND_EXTERNAL:
        return [path for path in source_raw_targets(project_id, [source_path]) if path.exists()]
    if source_kind == SOURCE_KIND_PROJECT:
        raw_source = Path(source_path)
        return [raw_source] if raw_source.exists() else []
    return []


def material_target_for_raw(raw_root: Path, materials_root: Path, raw_source: Path) -> Path:
    try:
        relative_path = raw_source.resolve().relative_to(raw_root.resolve())
    except ValueError:
        return materials_root / raw_source.name
    return materials_root / relative_path


def raw_relative_path(raw_root: Path, raw_source: Path) -> str:
    try:
        return raw_source.resolve().relative_to(raw_root.resolve()).as_posix()
    except ValueError:
        return raw_source.name


def external_source_is_newer(source: Path, raw_pairs: list[tuple[Path, Path]]) -> bool:
    try:
        if source.is_file():
            if not raw_pairs:
                return False
            return source.stat().st_mtime > raw_pairs[0][1].stat().st_mtime
        if source.is_dir():
            return any(
                source_path.stat().st_mtime > raw_target.stat().st_mtime
                for source_path, raw_target in raw_pairs
            )
    except OSError:
        return False
    return False
