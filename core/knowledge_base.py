from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.models import ChunkExtractionResult
from utils.paths import ensure_project_tree


def root_path(project_id: str) -> Path:
    return ensure_project_tree(project_id).knowledge_base


def source_manifest_path(project_id: str) -> Path:
    return root_path(project_id) / "source_manifest.json"


def seasons_root_path(project_id: str) -> Path:
    return root_path(project_id) / "seasons"


def season_path(project_id: str, season_id: str) -> Path:
    return seasons_root_path(project_id) / season_id


def episodes_root_path(project_id: str, season_id: str) -> Path:
    return season_path(project_id, season_id) / "episodes"


def episode_path(project_id: str, season_id: str, episode_id: str) -> Path:
    return episodes_root_path(project_id, season_id) / episode_id


def chunks_root_path(project_id: str, season_id: str, episode_id: str) -> Path:
    return episode_path(project_id, season_id, episode_id) / "chunks"


def chunk_result_path(project_id: str, result: ChunkExtractionResult) -> Path:
    return chunks_root_path(project_id, result.season_id, result.episode_id) / f"{result.chunk_id}.json"


def episode_content_path(project_id: str, season_id: str, episode_id: str) -> Path:
    return episode_path(project_id, season_id, episode_id) / "episode_content.json"


def episode_summary_path(project_id: str, season_id: str, episode_id: str) -> Path:
    return episode_path(project_id, season_id, episode_id) / "episode_summary.json"


def season_content_path(project_id: str, season_id: str) -> Path:
    return season_path(project_id, season_id) / "season_content.json"


def season_summary_path(project_id: str, season_id: str) -> Path:
    return season_path(project_id, season_id) / "season_summary.json"


def character_stage_states_path(project_id: str, season_id: str) -> Path:
    return season_path(project_id, season_id) / "character_stage_states.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_object(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_source_manifest(project_id: str, manifest: dict[str, Any]) -> Path:
    return write_json(source_manifest_path(project_id), manifest)


def load_source_manifest(project_id: str) -> dict[str, Any]:
    path = source_manifest_path(project_id)
    if not path.exists():
        raise ValueError("source manifest not found; generate source_manifest.json first")
    return read_json_object(path)


def initialize_structure(project_id: str, manifest: dict[str, Any] | None = None) -> Path:
    manifest_data = manifest if manifest is not None else load_source_manifest(project_id)
    seasons_root = seasons_root_path(project_id)
    for season in manifest_data.get("seasons", []):
        if not isinstance(season, dict):
            continue
        season_id = season.get("season_id")
        if not isinstance(season_id, str) or not season_id.strip():
            continue
        for episode in season.get("episodes", []):
            if not isinstance(episode, dict):
                continue
            episode_id = episode.get("episode_id")
            if not isinstance(episode_id, str) or not episode_id.strip():
                continue
            chunks_root_path(project_id, season_id, episode_id).mkdir(parents=True, exist_ok=True)
    return seasons_root


def save_chunk_result(project_id: str, result: ChunkExtractionResult) -> Path:
    return write_json(chunk_result_path(project_id, result), result.model_dump(mode="json"))


def load_chunk_result(path: Path) -> ChunkExtractionResult:
    return ChunkExtractionResult.model_validate(read_json(path))


def list_chunk_result_paths(project_id: str, *, include_legacy_top_level: bool = True) -> list[Path]:
    knowledge_base = root_path(project_id)
    chunk_paths: list[Path] = []
    seasons_root = seasons_root_path(project_id)
    if seasons_root.exists():
        chunk_paths.extend(
            [
                path
                for path in seasons_root.rglob("*.json")
                if path.is_file() and "chunks" in path.parts
            ]
        )
    top_level_chunks = knowledge_base / "chunks"
    if include_legacy_top_level and top_level_chunks.exists():
        chunk_paths.extend([path for path in top_level_chunks.rglob("*.json") if path.is_file()])
    return sorted(
        list({path.resolve(): path for path in chunk_paths}.values()),
        key=lambda path: path.relative_to(knowledge_base).as_posix().lower(),
    )


def list_season_dirs(project_id: str) -> list[Path]:
    return _sorted_dirs(seasons_root_path(project_id))


def list_episode_dirs(project_id: str, season_id: str) -> list[Path]:
    return _sorted_dirs(episodes_root_path(project_id, season_id))


def save_episode_content(
    project_id: str,
    season_id: str,
    episode_id: str,
    payload: dict[str, Any],
) -> Path:
    return write_json(episode_content_path(project_id, season_id, episode_id), payload)


def load_episode_content(project_id: str, season_id: str, episode_id: str) -> dict[str, Any]:
    return read_json_object(episode_content_path(project_id, season_id, episode_id))


def save_episode_summary(
    project_id: str,
    season_id: str,
    episode_id: str,
    payload: dict[str, Any],
) -> Path:
    return write_json(episode_summary_path(project_id, season_id, episode_id), payload)


def load_episode_summary(project_id: str, season_id: str, episode_id: str) -> dict[str, Any]:
    return read_json_object(episode_summary_path(project_id, season_id, episode_id))


def save_season_content(project_id: str, season_id: str, payload: dict[str, Any]) -> Path:
    return write_json(season_content_path(project_id, season_id), payload)


def load_season_content(project_id: str, season_id: str) -> dict[str, Any]:
    return read_json_object(season_content_path(project_id, season_id))


def save_season_summary(project_id: str, season_id: str, payload: dict[str, Any]) -> Path:
    return write_json(season_summary_path(project_id, season_id), payload)


def load_season_summary(project_id: str, season_id: str) -> dict[str, Any]:
    return read_json_object(season_summary_path(project_id, season_id))


def load_current_season_episode_summaries(
    project_id: str,
    season_id: str,
    current_episode_id: str,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for episode_dir in list_episode_dirs(project_id, season_id):
        episode_id = episode_dir.name
        if episode_id >= current_episode_id:
            continue
        path = episode_summary_path(project_id, season_id, episode_id)
        if not path.exists():
            continue
        payload = read_json(path)
        if isinstance(payload, dict):
            summaries.append(payload)
    return summaries


def load_previous_season_summary(
    project_id: str,
    season_id: str,
    *,
    enabled: bool = True,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    try:
        season_index = int(season_id.split("_")[-1])
    except (ValueError, IndexError):
        return None
    if season_index <= 1:
        return None

    previous_season_id = f"season_{season_index - 1:03d}"
    path = season_summary_path(project_id, previous_season_id)
    if not path.exists():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def load_character_stage_states(project_id: str, season_id: str) -> dict[str, Any]:
    path = character_stage_states_path(project_id, season_id)
    if not path.exists():
        return {"season_id": season_id, "characters": {}}
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {"season_id": season_id, "characters": {}}
    characters = payload.get("characters")
    if isinstance(characters, dict):
        return {"season_id": payload.get("season_id", season_id), "characters": characters}
    character = payload.get("character")
    if isinstance(character, str) and character:
        return {
            "season_id": payload.get("season_id", season_id),
            "characters": {
                character: {
                    "stage_states": payload.get("stage_states", []),
                    "final_state": payload.get("final_state", {}),
                }
            },
        }
    return {"season_id": payload.get("season_id", season_id), "characters": {}}


def save_character_stage_states(project_id: str, season_id: str, payload: dict[str, Any]) -> Path:
    return write_json(character_stage_states_path(project_id, season_id), payload)


def _sorted_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([path for path in root.iterdir() if path.is_dir()], key=lambda path: path.name.lower())
