from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.paths import ensure_project_tree


VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
FORMAL_VIDEO_SCHEMA_VERSION = 1
FORMAL_VIDEO_SOURCE_KIND = "video"
FORMAL_VIDEO_SCAN_TYPE = "formal_video"
TRANSCODED_VIDEO_NAME = "transcoded.mp4"
SEGMENT_VIDEO_PREFIX = "segment_"


def scan_source_directory(source_root: str) -> dict[str, Any]:
    root = Path(source_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"source root does not exist or is not a directory: {source_root}")

    season_dirs = sorted(
        [path for path in root.iterdir() if path.is_dir()],
        key=lambda path: path.name.lower(),
    )

    seasons: list[dict[str, Any]] = []
    for season_index, season_dir in enumerate(season_dirs, start=1):
        episode_files = sorted(
            [
                file_path
                for file_path in season_dir.iterdir()
                if file_path.is_file() and file_path.suffix.lower() in VIDEO_SUFFIXES
            ],
            key=lambda path: path.name.lower(),
        )
        episodes: list[dict[str, str]] = []
        for episode_index, episode_file in enumerate(episode_files, start=1):
            episodes.append(
                {
                    "episode_id": f"episode_{episode_index:03d}",
                    "source_file": str(episode_file.resolve()),
                    "display_title": episode_file.name,
                    "sort_key": episode_file.name.lower(),
                }
            )
        seasons.append(
            {
                "season_id": f"season_{season_index:03d}",
                "source_folder": str(season_dir.resolve()),
                "display_title": season_dir.name,
                "sort_key": season_dir.name.lower(),
                "episodes": episodes,
            }
        )

    return {
        "source_root": str(root.resolve()),
        "seasons": seasons,
    }


def scan_formal_video_materials(project_id: str) -> dict[str, Any]:
    materials_root = ensure_project_tree(project_id).materials
    root_episode_candidates = _root_episode_candidates(materials_root)
    season_candidates = _season_candidates(materials_root)

    seasons: list[dict[str, Any]] = []
    if root_episode_candidates:
        seasons.append(
            _build_season_entry(
                season_index=1,
                materials_root=materials_root,
                source_path=".",
                display_title=materials_root.name,
                sort_key="",
                episode_candidates=root_episode_candidates,
            )
        )

    season_offset = len(seasons)
    for season_index, season_candidate in enumerate(season_candidates, start=season_offset + 1):
        seasons.append(
            _build_season_entry(
                season_index=season_index,
                materials_root=materials_root,
                source_path=season_candidate["source_path"],
                display_title=season_candidate["display_title"],
                sort_key=season_candidate["sort_key"],
                episode_candidates=season_candidate["episodes"],
            )
        )

    return {
        "schema_version": FORMAL_VIDEO_SCHEMA_VERSION,
        "source_kind": FORMAL_VIDEO_SOURCE_KIND,
        "scan_type": FORMAL_VIDEO_SCAN_TYPE,
        "source_root": str(materials_root.resolve()),
        "seasons": seasons,
    }


def collect_preview_video_chunks(project_id: str, *, limit: int) -> list[Path]:
    materials_root = ensure_project_tree(project_id).materials
    if not materials_root.exists():
        return []
    return sorted(
        [
            path
            for path in materials_root.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        ],
        key=lambda path: path.relative_to(materials_root).as_posix().lower(),
    )[:limit]


def preview_chunk_identity(project_id: str, video_path: Path, fallback_index: int) -> tuple[str, str, str]:
    materials_root = ensure_project_tree(project_id).materials
    season_id = "season_001"
    episode_id = f"episode_{fallback_index:03d}"
    try:
        relative_path = video_path.relative_to(materials_root)
    except ValueError:
        return (season_id, episode_id, video_path.stem or f"chunk_{fallback_index:03d}")

    if len(relative_path.parts) > 1:
        episode_folders = sorted(
            [path for path in materials_root.iterdir() if path.is_dir()],
            key=lambda path: path.name.lower(),
        )
        parent = materials_root / relative_path.parts[0]
        try:
            episode_index = episode_folders.index(parent) + 1
        except ValueError:
            episode_index = fallback_index
        episode_id = f"episode_{episode_index:03d}"

    chunk_id = video_path.stem or f"chunk_{fallback_index:03d}"
    return (season_id, episode_id, chunk_id)


def _root_episode_candidates(materials_root: Path) -> list[dict[str, Any]]:
    candidates = [
        _single_video_episode_candidate(materials_root, path)
        for path in _direct_video_files(materials_root)
    ]
    candidates.extend(
        _episode_directory_candidate(materials_root, path)
        for path in _direct_dirs(materials_root)
        if _is_episode_directory(path)
    )
    return _sort_episode_candidates(candidates)


def _season_candidates(materials_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for season_dir in _direct_dirs(materials_root):
        if _is_episode_directory(season_dir):
            continue

        episode_candidates = _episode_candidates_from_season_dir(materials_root, season_dir)
        if not episode_candidates:
            continue

        source_path = _relative_material_path(materials_root, season_dir)
        candidates.append(
            {
                "source_path": source_path,
                "display_title": season_dir.name,
                "sort_key": source_path.lower(),
                "episodes": episode_candidates,
            }
        )
    return sorted(candidates, key=lambda candidate: candidate["sort_key"])


def _episode_candidates_from_season_dir(materials_root: Path, season_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        _single_video_episode_candidate(materials_root, path)
        for path in _direct_video_files(season_dir)
    ]
    candidates.extend(
        _episode_directory_candidate(materials_root, path)
        for path in _direct_dirs(season_dir)
        if _is_episode_directory(path)
    )
    return _sort_episode_candidates(candidates)


def _single_video_episode_candidate(materials_root: Path, video_path: Path) -> dict[str, Any]:
    source_path = _relative_material_path(materials_root, video_path)
    return {
        "source_path": source_path,
        "display_title": video_path.name,
        "sort_key": source_path.lower(),
        "chunk_paths": [video_path],
    }


def _episode_directory_candidate(materials_root: Path, episode_dir: Path) -> dict[str, Any]:
    source_path = _relative_material_path(materials_root, episode_dir)
    return {
        "source_path": source_path,
        "display_title": episode_dir.name,
        "sort_key": source_path.lower(),
        "chunk_paths": _episode_directory_chunk_paths(episode_dir),
    }


def _build_season_entry(
    *,
    season_index: int,
    materials_root: Path,
    source_path: str,
    display_title: str,
    sort_key: str,
    episode_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    episodes = [
        _build_episode_entry(episode_index, materials_root, episode_candidate)
        for episode_index, episode_candidate in enumerate(episode_candidates, start=1)
    ]
    return {
        "season_id": f"season_{season_index:03d}",
        "source_path": source_path,
        "display_title": display_title,
        "sort_key": sort_key,
        "episodes": episodes,
    }


def _build_episode_entry(
    episode_index: int,
    materials_root: Path,
    episode_candidate: dict[str, Any],
) -> dict[str, Any]:
    chunk_paths = episode_candidate["chunk_paths"]
    chunks = [
        _build_chunk_entry(chunk_index, materials_root, chunk_path)
        for chunk_index, chunk_path in enumerate(chunk_paths, start=1)
    ]
    return {
        "episode_id": f"episode_{episode_index:03d}",
        "source_kind": FORMAL_VIDEO_SOURCE_KIND,
        "source_path": episode_candidate["source_path"],
        "display_title": episode_candidate["display_title"],
        "sort_key": episode_candidate["sort_key"],
        "chunks": chunks,
    }


def _build_chunk_entry(chunk_index: int, materials_root: Path, chunk_path: Path) -> dict[str, Any]:
    source_path = _relative_material_path(materials_root, chunk_path)
    return {
        "chunk_id": f"chunk_{chunk_index:04d}",
        "source_kind": FORMAL_VIDEO_SOURCE_KIND,
        "source_path": source_path,
        "display_title": chunk_path.name,
        "sort_key": source_path.lower(),
    }


def _is_episode_directory(directory: Path) -> bool:
    return bool(_episode_directory_chunk_paths(directory))


def _episode_directory_chunk_paths(directory: Path) -> list[Path]:
    segment_files = [
        path
        for path in _direct_video_files(directory)
        if path.name.lower().startswith(SEGMENT_VIDEO_PREFIX)
    ]
    if segment_files:
        return _sort_paths(segment_files)

    transcoded_files = [
        path
        for path in _direct_video_files(directory)
        if path.name.lower() == TRANSCODED_VIDEO_NAME
    ]
    return _sort_paths(transcoded_files[:1])


def _direct_video_files(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return _sort_paths(
        [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        ]
    )


def _direct_dirs(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return _sort_paths([path for path in directory.iterdir() if path.is_dir()])


def _sort_paths(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda path: path.name.lower())


def _sort_episode_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda candidate: candidate["sort_key"])


def _relative_material_path(materials_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(materials_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
