from __future__ import annotations

import logging
from pathlib import Path
from collections import defaultdict

from core import knowledge_base as kb
from core.models import CharacterState
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, build_model_call_request
from utils.i18n import t


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
    state = CharacterState(character=character, summary="", evidence_count=0, conflicts=[])
    timeline: list[dict] = []

    for season_dir in kb.list_season_dirs(project_id):
        for episode_dir in kb.list_episode_dirs(project_id, season_dir.name):
            episode_content_path = kb.episode_content_path(project_id, season_dir.name, episode_dir.name)
            if not episode_content_path.exists():
                continue
            try:
                payload = kb.load_episode_content(project_id, season_dir.name, episode_dir.name)
            except (OSError, ValueError):
                LOGGER.warning(
                    "Episode content read failed; project_id=%s season_id=%s episode_id=%s",
                    project_id,
                    season_dir.name,
                    episode_dir.name,
                    exc_info=True,
                )
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


def compile_character_state_from_knowledge_base(
    project_id: str,
    character: str,
) -> CharacterState | None:
    compiled = compile_character_state_by_season_episode(project_id, character)
    timeline = compiled.get("timeline", [])
    if not timeline:
        return None
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


def write_character_stage_states(project_id: str, character: str) -> list[Path]:
    compiled = compile_character_state_by_season_episode(project_id, character)
    timeline = compiled.get("timeline", [])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in timeline:
        season_id = item.get("season_id")
        if not isinstance(season_id, str):
            continue
        grouped[season_id].append(item)

    written_paths: list[Path] = []
    for season_id in sorted(grouped.keys()):
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
        output = kb.load_character_stage_states(project_id, season_id)
        characters = output.setdefault("characters", {})
        characters[character] = {
            "stage_states": stage_entries,
            "final_state": stage_entries[-1]["state"] if stage_entries else {},
        }
        written_paths.append(kb.save_character_stage_states(project_id, season_id, output))
    return written_paths


def final_polish_character_state(project_id: str, character: str) -> CharacterState:
    return compile_character_state_from_knowledge_base(project_id, character) or CharacterState(
        character=character
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


def _polish_summary(summary: str) -> str:
    if not summary.strip():
        return summary
    parts = [item.strip() for item in summary.split(";") if item.strip()]
    return "; ".join(dict.fromkeys(parts))
