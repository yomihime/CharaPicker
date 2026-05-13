from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.paths import ensure_project_tree


VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}


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
