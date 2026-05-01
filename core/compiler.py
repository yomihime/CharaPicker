from __future__ import annotations

import logging
import json
from pathlib import Path

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


def _sorted_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([path for path in root.iterdir() if path.is_dir()], key=lambda path: path.name.lower())
