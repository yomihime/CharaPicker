from __future__ import annotations

import logging
import json
from pathlib import Path
from collections import defaultdict

from core.models import CharacterState
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, build_model_call_request
from utils.i18n import t
from utils.paths import ensure_project_tree


LOGGER = logging.getLogger(__name__)


def build_character_compile_request(
    character: str,
    current_state: CharacterState,
    evidence_chunk: str,
    *,
    backend: ModelBackend,
    model_name: str,
    base_url: str = "",
    api_key: str = "",
) -> ModelCallRequest:
    return build_model_call_request(
        purpose="character_compile",
        backend=backend,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        variables={
            "character": character,
            "current_state": current_state,
            "evidence_chunk": evidence_chunk,
        },
        metadata={"character": character},
    )


def compile_character_state(character: str) -> CharacterState:
    LOGGER.info("Character state compilation started; character=%s", character)
    return CharacterState(
        character=character,
        summary=t("compiler.placeholder.summary"),
    )


def compile_character_state_by_season_episode(project_id: str, character: str) -> dict:
    knowledge_base = ensure_project_tree(project_id).knowledge_base
    seasons_root = knowledge_base / "seasons"
    state = CharacterState(character=character, summary="", evidence_count=0, conflicts=[])
    timeline: list[dict] = []

    for season_dir in _sorted_dirs(seasons_root):
        episodes_root = season_dir / "episodes"
        for episode_dir in _sorted_dirs(episodes_root):
            episode_content_path = episode_dir / "episode_content.json"
            if not episode_content_path.exists():
                continue
            payload = json.loads(episode_content_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            if not _episode_targets_character(payload, character):
                continue

            state = _apply_episode_payload_to_state(state, payload)
            timeline.append(
                {
                    "season_id": season_dir.name,
                    "episode_id": episode_dir.name,
                    "state": state.model_dump(mode="json"),
                }
            )

    return {
        "character": character,
        "final_state": state.model_dump(mode="json"),
        "timeline": timeline,
    }


def write_character_stage_states(project_id: str, character: str) -> list[Path]:
    compiled = compile_character_state_by_season_episode(project_id, character)
    timeline = compiled.get("timeline", [])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in timeline:
        season_id = item.get("season_id")
        if not isinstance(season_id, str):
            continue
        grouped[season_id].append(item)

    knowledge_base = ensure_project_tree(project_id).knowledge_base
    written_paths: list[Path] = []
    for season_id in sorted(grouped.keys()):
        season_dir = knowledge_base / "seasons" / season_id
        season_dir.mkdir(parents=True, exist_ok=True)
        stage_entries: list[dict] = []
        for step in grouped[season_id]:
            episode_id = step.get("episode_id", "")
            state_payload = step.get("state", {})
            if not isinstance(state_payload, dict):
                continue
            stage_entries.append(
                {
                    "season_id": season_id,
                    "episode_id": episode_id,
                    "character": character,
                    "state": state_payload,
                }
            )
        output_path = season_dir / "character_stage_states.json"
        output = _load_character_stage_states(output_path, season_id)
        characters = output.setdefault("characters", {})
        characters[character] = {
            "stage_states": stage_entries,
            "final_state": stage_entries[-1]["state"] if stage_entries else {},
        }
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        written_paths.append(output_path)
    return written_paths


def final_polish_character_state(project_id: str, character: str) -> CharacterState:
    compiled = compile_character_state_by_season_episode(project_id, character)
    final_state_payload = compiled.get("final_state", {})
    final_state = CharacterState.model_validate(final_state_payload)
    polished_summary = _polish_summary(final_state.summary)
    polished_conflicts = list(dict.fromkeys([item.strip() for item in final_state.conflicts if item.strip()]))
    polished_evidence_count = max(0, int(final_state.evidence_count))
    return CharacterState(
        character=final_state.character,
        summary=polished_summary,
        evidence_count=polished_evidence_count,
        conflicts=polished_conflicts,
    )


def _apply_episode_payload_to_state(state: CharacterState, payload: dict) -> CharacterState:
    facts = [item for item in payload.get("facts", []) if isinstance(item, str) and item.strip()]
    behavior_traits = [
        item for item in payload.get("behavior_traits", []) if isinstance(item, str) and item.strip()
    ]
    conflicts = [item for item in payload.get("conflicts", []) if isinstance(item, str) and item.strip()]

    summary_parts = [part for part in [state.summary, "; ".join(behavior_traits)] if part]
    merged_conflicts = list(dict.fromkeys([*state.conflicts, *conflicts]))
    return CharacterState(
        character=state.character,
        summary="; ".join(summary_parts),
        evidence_count=state.evidence_count + len(facts),
        conflicts=merged_conflicts,
    )


def _episode_targets_character(payload: dict, character: str) -> bool:
    targets = payload.get("targets", [])
    if not isinstance(targets, list) or not targets:
        return True
    normalized_character = character.strip()
    return any(isinstance(item, str) and item.strip() == normalized_character for item in targets)


def _load_character_stage_states(path: Path, season_id: str) -> dict:
    if not path.exists():
        return {"season_id": season_id, "characters": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def _sorted_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([path for path in root.iterdir() if path.is_dir()], key=lambda path: path.name.lower())


def _polish_summary(summary: str) -> str:
    if not summary.strip():
        return summary
    parts = [item.strip() for item in summary.split(";") if item.strip()]
    return "; ".join(dict.fromkeys(parts))
