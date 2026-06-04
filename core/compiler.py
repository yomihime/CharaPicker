from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

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


def compile_character_state_by_season_episode(
    project_id: str,
    character: str,
    aliases: Iterable[str] | None = None,
) -> dict:
    return _compile_character_state_by_season_episode(
        project_id,
        character,
        aliases=aliases,
        content_path=kb.episode_content_path,
        load_content=kb.load_episode_content,
        log_label="Episode content",
        required_stage=kb.FULL_EXTRACTION_STAGE,
    )


def compile_preview_character_state_from_knowledge_base(
    project_id: str,
    character: str,
) -> CharacterState | None:
    compiled = _compile_character_state_by_season_episode(
        project_id,
        character,
        aliases=None,
        content_path=kb.preview_episode_content_path,
        load_content=kb.load_preview_episode_content,
        log_label="Preview episode content",
    )
    return _character_state_from_compiled(compiled)


def _compile_character_state_by_season_episode(
    project_id: str,
    character: str,
    *,
    aliases: Iterable[str] | None,
    content_path: Callable[[str, str, str], Path],
    load_content: Callable[[str, str, str], dict],
    log_label: str,
    required_stage: str | None = None,
) -> dict:
    state = CharacterState(character=character, summary="", evidence_count=0, conflicts=[])
    timeline: list[dict] = []
    match_terms = _character_match_terms(character, aliases)

    for season_dir in kb.list_season_dirs(project_id):
        for episode_dir in kb.list_episode_dirs(project_id, season_dir.name):
            episode_content_path = content_path(project_id, season_dir.name, episode_dir.name)
            if not episode_content_path.exists():
                continue
            try:
                payload = load_content(project_id, season_dir.name, episode_dir.name)
            except (OSError, ValueError):
                LOGGER.warning(
                    "%s read failed; project_id=%s season_id=%s episode_id=%s",
                    log_label,
                    project_id,
                    season_dir.name,
                    episode_dir.name,
                    exc_info=True,
                )
                continue
            if required_stage is not None and kb.artifact_stage_from_payload(payload) != required_stage:
                LOGGER.warning(
                    "%s skipped because it is not a %s artifact; project_id=%s season_id=%s episode_id=%s stage=%s",
                    log_label,
                    required_stage,
                    project_id,
                    season_dir.name,
                    episode_dir.name,
                    kb.artifact_stage_from_payload(payload),
                )
                continue
            if not _episode_targets_character(payload, match_terms):
                continue

            state = _apply_episode_payload_to_state(state, payload, match_terms)
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
    return _character_state_from_compiled(compiled)


def _character_state_from_compiled(compiled: dict) -> CharacterState | None:
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


def _apply_episode_payload_to_state(
    state: CharacterState,
    payload: dict,
    match_terms: list[str],
) -> CharacterState:
    facts = _character_related_items(payload.get("facts", []), match_terms)
    behavior_traits = _character_related_items(payload.get("behavior_traits", []), match_terms)
    dialogue_style = _character_related_items(payload.get("dialogue_style", []), match_terms)
    relationship_interactions = _character_related_items(
        payload.get("relationship_interactions", []),
        match_terms,
    )
    character_state_changes = _character_related_items(
        payload.get("character_state_changes", []),
        match_terms,
    )
    conflicts = _character_related_items(payload.get("conflicts", []), match_terms)
    if not any(
        [
            facts,
            behavior_traits,
            dialogue_style,
            relationship_interactions,
            character_state_changes,
            conflicts,
        ]
    ):
        return state

    summary_items = [
        *behavior_traits,
        *dialogue_style,
        *relationship_interactions,
        *character_state_changes,
    ] or facts
    summary_parts = [part for part in [state.summary, "; ".join(summary_items)] if part]
    merged_conflicts = list(dict.fromkeys([*state.conflicts, *conflicts]))
    return CharacterState(
        character=state.character,
        summary="; ".join(summary_parts),
        evidence_count=state.evidence_count + len(facts),
        conflicts=merged_conflicts,
    )


def _episode_targets_character(payload: dict, match_terms: list[str]) -> bool:
    targets = payload.get("targets", [])
    if not isinstance(targets, list) or not targets:
        return True
    return any(isinstance(item, str) and _text_matches_any_term(item, match_terms) for item in targets)


def _character_related_items(value: object, match_terms: list[str]) -> list[str]:
    if not match_terms or not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and _text_matches_any_term(text, match_terms):
            output.append(text)
    return output


def _character_match_terms(character: str, aliases: Iterable[str] | None) -> list[str]:
    alias_values = [aliases] if isinstance(aliases, str) else list(aliases or [])
    values = [character, *alias_values]
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        terms.append(text)
        seen.add(key)
    return terms


def _text_matches_any_term(text: str, match_terms: list[str]) -> bool:
    normalized_text = text.strip().casefold()
    if not normalized_text:
        return False
    for term in match_terms:
        normalized_term = term.strip().casefold()
        if len(normalized_term) < 2:
            continue
        if normalized_term in normalized_text:
            return True
    return False


def _polish_summary(summary: str) -> str:
    if not summary.strip():
        return summary
    parts = [item.strip() for item in summary.split(";") if item.strip()]
    return "; ".join(dict.fromkeys(parts))
