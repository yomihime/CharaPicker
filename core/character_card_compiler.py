from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core import character_card_store as store
from core import knowledge_base as kb
from core.compiler import compile_character_state_by_season_episode
from core.models import (
    CharacterCard,
    CharacterCardBook,
    CharacterCardCompileSource,
    CharacterCardCompileTarget,
    CharacterCardDialogue,
    CharacterCardKind,
    CharacterCardProfile,
    CharacterCardPromptSurfaces,
    CharacterCardStatus,
)
from utils.ai_model_middleware import build_model_call_request, call_text_model
from utils.cloud_model_presets import CloudModelPreset, cloud_model_provider


LOGGER = logging.getLogger(__name__)
CHARACTER_CARD_COMPILE_PROMPT = "character_card_compile"


def build_compile_target(card: CharacterCard) -> CharacterCardCompileTarget:
    character_name = card.identity.character_name.strip()
    if not character_name:
        raise ValueError("character name is required before compiling")
    return CharacterCardCompileTarget(
        project_id=card.project_id,
        card_id=card.card_id,
        character_name=character_name,
        compile_source=CharacterCardCompileSource.KNOWLEDGE_BASE,
    )


def compile_card_from_knowledge_base(
    card: CharacterCard,
    *,
    cloud_preset: CloudModelPreset | None = None,
) -> CharacterCard:
    target = build_compile_target(card)
    episode_payloads = _collect_episode_payloads(
        target.project_id,
        content_path=kb.episode_content_path,
        load_content=kb.load_episode_content,
        require_full=True,
    )
    if not episode_payloads:
        raise ValueError("formal knowledge base is not available")

    compiled = compile_character_state_by_season_episode(target.project_id, target.character_name)
    timeline = compiled.get("timeline", [])
    if not timeline:
        raise ValueError("character was not found in the formal knowledge base")

    final_state = compiled.get("final_state", {})
    if not isinstance(final_state, dict):
        raise ValueError("compiled character state is invalid")
    if cloud_preset is None:
        raise ValueError("cloud text model preset is required for character card compilation")

    output = card.model_copy(deep=True)
    output.card_kind = CharacterCardKind.OFFICIAL
    output.compile_status = CharacterCardStatus.COMPILED
    output.compile_source = CharacterCardCompileSource.KNOWLEDGE_BASE
    output.compiled_at = datetime.now()
    output.source_context.compiled_from_preview = False
    output.source_context.knowledge_base_ref = "seasons"
    _apply_compiled_state(output, final_state, timeline, episode_payloads)
    _review_card_with_ai(output, final_state, timeline, episode_payloads, cloud_preset)
    return output


def compile_preview_card_from_preview_knowledge_base(project_id: str, character_name: str = "") -> CharacterCard:
    name = character_name.strip() or _guess_preview_character(project_id)
    card = store.create_preview_card(project_id, name)
    episode_payloads = _collect_episode_payloads(
        project_id,
        content_path=kb.preview_episode_content_path,
        load_content=kb.load_preview_episode_content,
        require_full=False,
    )
    if not episode_payloads:
        raise ValueError("preview knowledge base is not available")

    timeline: list[dict] = []
    state = {
        "character": name,
        "summary": "",
        "evidence_count": 0,
        "conflicts": [],
    }
    for season_id, episode_id, payload in episode_payloads:
        state = _apply_payload_to_simple_state(state, payload, name)
        timeline.append({"season_id": season_id, "episode_id": episode_id, "state": dict(state)})
    _apply_compiled_state(card, state, timeline, episode_payloads)
    card.compile_status = CharacterCardStatus.PREVIEW
    card.compile_source = CharacterCardCompileSource.PREVIEW
    card.compiled_at = datetime.now()
    return card


def collect_compile_warnings(card: CharacterCard) -> list[str]:
    warnings = [*card.quality.warnings, *card.evidence.warnings]
    if not card.profile.summary.strip():
        warnings.append("summary is empty")
    if card.evidence.evidence_count <= 0:
        warnings.append("no evidence was matched")
    return list(dict.fromkeys(warnings))


def _apply_compiled_state(
    card: CharacterCard,
    final_state: dict,
    timeline: list[dict],
    episode_payloads: list[tuple[str, str, dict]],
) -> None:
    character = str(final_state.get("character") or card.identity.character_name or card.identity.display_name)
    summary = str(final_state.get("summary") or "")
    conflicts = [str(item) for item in final_state.get("conflicts", []) if str(item).strip()]
    evidence_count = int(final_state.get("evidence_count") or 0)
    refs: list[str] = []
    behavior: list[str] = []
    speech: list[str] = []
    relationships: list[dict] = []
    included_seasons: list[str] = []
    included_episodes: list[str] = []
    included_chunks: list[str] = []
    for season_id, episode_id, payload in episode_payloads:
        included_seasons.append(season_id)
        included_episodes.append(f"{season_id}/{episode_id}")
        refs.extend(str(item) for item in payload.get("evidence_refs", []) if str(item).strip())
        behavior.extend(_related_items(payload.get("behavior_traits", []), character))
        speech.extend(_related_items(payload.get("dialogue_style", []), character))
        for item in _related_items(payload.get("relationship_interactions", []), character):
            relationships.append({"description": item, "season_id": season_id, "episode_id": episode_id})
        for chunk in payload.get("chunk_results", []):
            if isinstance(chunk, dict):
                chunk_id = chunk.get("chunk_id")
                if isinstance(chunk_id, str) and chunk_id:
                    included_chunks.append(f"{season_id}/{episode_id}/{chunk_id}")
    card.identity.character_name = character
    if not card.identity.display_name:
        card.identity.display_name = character
    card.profile.summary = summary
    card.profile.long_description = summary
    card.profile.personality_traits = _unique(behavior)
    card.profile.speech_style = _unique(speech)
    card.profile.current_state = summary
    card.prompt_surfaces.persona_prompt = summary
    card.prompt_surfaces.system_prompt = _build_system_prompt(card)
    card.timeline = timeline
    card.relationships = relationships
    card.evidence.evidence_count = evidence_count
    card.evidence.refs = _unique(refs)
    card.evidence.conflicts = _unique(conflicts)
    card.evidence.warnings = collect_compile_warnings(card)
    card.quality.warnings = _unique(conflicts)
    card.source_context.included_seasons = _unique(included_seasons)
    card.source_context.included_episodes = _unique(included_episodes)
    card.source_context.included_chunks = _unique(included_chunks)
    card.revision += 1


def _review_card_with_ai(
    card: CharacterCard,
    final_state: dict,
    timeline: list[dict],
    episode_payloads: list[tuple[str, str, dict]],
    cloud_preset: CloudModelPreset,
) -> None:
    request = build_model_call_request(
        purpose=CHARACTER_CARD_COMPILE_PROMPT,
        backend=cloud_model_provider(cloud_preset.provider).backend_for("text"),
        model_name=cloud_preset.model_name,
        base_url=cloud_preset.base_url,
        api_key=cloud_preset.api_key,
        max_tokens=cloud_preset.max_output_tokens,
        variables={
            "character": card.identity.character_name,
            "current_card": card.model_dump(mode="json"),
            "knowledge_summary": _build_ai_knowledge_summary(card, final_state, timeline, episode_payloads),
            "extra_requirements": card.user_metadata.compile_requirements or "None",
            "response_schema": _character_card_response_schema(),
        },
        metadata={
            "project_id": card.project_id,
            "card_id": card.card_id,
            "character": card.identity.character_name,
        },
    )
    result = call_text_model(request)
    payload = _parse_json_object(result.content)
    _apply_ai_card_payload(card, payload)
    card.source_context.prompt_profile_id = CHARACTER_CARD_COMPILE_PROMPT
    card.source_context.model_profile_id = cloud_preset.name


def _build_ai_knowledge_summary(
    card: CharacterCard,
    final_state: dict,
    timeline: list[dict],
    episode_payloads: list[tuple[str, str, dict]],
) -> dict[str, Any]:
    character = card.identity.character_name
    episodes: list[dict[str, Any]] = []
    for season_id, episode_id, payload in episode_payloads:
        episodes.append(
            {
                "season_id": season_id,
                "episode_id": episode_id,
                "facts": _related_items(payload.get("facts", []), character)[:60],
                "behavior_traits": _related_items(payload.get("behavior_traits", []), character)[:60],
                "dialogue_style": _related_items(payload.get("dialogue_style", []), character)[:40],
                "relationships": _related_items(
                    payload.get("relationship_interactions", payload.get("relationships", [])),
                    character,
                )[:40],
                "state_changes": _related_items(payload.get("character_state_changes", []), character)[:40],
                "conflicts": _related_items(payload.get("conflicts", []), character)[:30],
                "insight_summary": str(payload.get("insight_summary", "")),
                "evidence_refs": [str(item) for item in payload.get("evidence_refs", []) if str(item).strip()][:40],
            }
        )
    return {
        "final_state": final_state,
        "timeline": timeline,
        "episodes": episodes,
    }


def _character_card_response_schema() -> dict[str, Any]:
    return {
        "profile": {
            "summary": "string",
            "long_description": "string",
            "personality": "string",
            "personality_traits": ["string"],
            "speech_style": ["string"],
            "relationships_summary": "string",
            "current_state": "string",
            "scenario_default": "string",
            "world_context": "string",
            "uncertainties": ["string"],
        },
        "prompt_surfaces": {
            "system_prompt": "string",
            "persona_prompt": "string",
            "scenario": "string",
            "first_message": "string",
            "suggested_starters": ["string"],
            "custom_error_reply": "string",
            "creator_notes": "string",
        },
        "dialogue": {
            "first_message": "string",
            "suggested_starters": ["string"],
            "preset_dialogues": [
                {
                    "title": "string",
                    "messages": [{"role": "user|assistant", "content": "string"}],
                }
            ],
        },
        "character_book": {
            "entries": [{"keys": ["string"], "content": "string", "enabled": True, "insertion_order": 100}]
        },
        "relationships": [{"name": "string", "description": "string"}],
        "warnings": ["string"],
    }


def _apply_ai_card_payload(card: CharacterCard, payload: dict[str, Any]) -> None:
    profile = payload.get("profile")
    if isinstance(profile, dict):
        card.profile = CharacterCardProfile.model_validate(_merged_payload(card.profile, profile))

    prompt_surfaces = payload.get("prompt_surfaces")
    if isinstance(prompt_surfaces, dict):
        card.prompt_surfaces = CharacterCardPromptSurfaces.model_validate(
            _merged_payload(card.prompt_surfaces, prompt_surfaces)
        )

    dialogue = payload.get("dialogue")
    if isinstance(dialogue, dict):
        _normalize_dialogue_roles(dialogue)
        card.dialogue = CharacterCardDialogue.model_validate(_merged_payload(card.dialogue, dialogue))

    character_book = payload.get("character_book")
    if isinstance(character_book, dict):
        card.character_book = CharacterCardBook.model_validate(
            _merged_payload(card.character_book, character_book)
        )

    relationships = payload.get("relationships")
    if isinstance(relationships, list):
        card.relationships = [item for item in relationships if isinstance(item, dict)]

    warnings = payload.get("warnings", [])
    if isinstance(warnings, list):
        card.quality.warnings = _unique([*card.quality.warnings, *[str(item) for item in warnings]])
        card.evidence.warnings = collect_compile_warnings(card)

    if card.user_metadata.compile_requirements:
        requirements_note = "User requirements:\n" + card.user_metadata.compile_requirements
        card.prompt_surfaces.creator_notes = "\n\n".join(
            item
            for item in [
                card.prompt_surfaces.creator_notes,
                requirements_note if requirements_note not in card.prompt_surfaces.creator_notes else "",
            ]
            if item
        )


def _merged_payload(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    current = model.model_dump(mode="json")
    current.update(payload)
    return current


def _normalize_dialogue_roles(payload: dict[str, Any]) -> None:
    for key in ("example_dialogues", "preset_dialogues"):
        dialogues = payload.get(key)
        if not isinstance(dialogues, list):
            continue
        for dialogue in dialogues:
            if not isinstance(dialogue, dict):
                continue
            messages = dialogue.get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                if isinstance(role, str):
                    message["role"] = role.strip().lower()


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lstrip().startswith("json"):
            stripped = stripped.lstrip()[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("character card model response did not contain a JSON object")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("character card model response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("character card model response must be a JSON object")
    return payload


def _collect_episode_payloads(
    project_id: str,
    *,
    content_path: Callable[[str, str, str], Path],
    load_content: Callable[[str, str, str], dict],
    require_full: bool,
) -> list[tuple[str, str, dict]]:
    payloads: list[tuple[str, str, dict]] = []
    for season_dir in kb.list_season_dirs(project_id):
        for episode_dir in kb.list_episode_dirs(project_id, season_dir.name):
            path = content_path(project_id, season_dir.name, episode_dir.name)
            if not path.exists():
                continue
            try:
                payload = load_content(project_id, season_dir.name, episode_dir.name)
            except (OSError, ValueError, json.JSONDecodeError):
                LOGGER.warning(
                    "Episode content skipped during card compilation; project_id=%s path=%s",
                    project_id,
                    path,
                    exc_info=True,
                )
                continue
            if require_full and not kb.is_full_artifact_payload(payload):
                continue
            payloads.append((season_dir.name, episode_dir.name, payload))
    return payloads


def _apply_payload_to_simple_state(state: dict, payload: dict, character: str) -> dict:
    facts = _related_items(payload.get("facts", []), character)
    behavior = _related_items(payload.get("behavior_traits", []), character)
    speech = _related_items(payload.get("dialogue_style", []), character)
    relationships = _related_items(payload.get("relationship_interactions", []), character)
    changes = _related_items(payload.get("character_state_changes", []), character)
    conflicts = _related_items(payload.get("conflicts", []), character)
    summary_items = [*behavior, *speech, *relationships, *changes] or facts
    if summary_items:
        state["summary"] = "; ".join(_unique([state.get("summary", ""), *summary_items]))
    state["evidence_count"] = int(state.get("evidence_count") or 0) + len(facts)
    state["conflicts"] = _unique([*state.get("conflicts", []), *conflicts])
    return state


def _guess_preview_character(project_id: str) -> str:
    for season_id, episode_id, payload in _collect_episode_payloads(
        project_id,
        content_path=kb.preview_episode_content_path,
        load_content=kb.load_preview_episode_content,
        require_full=False,
    ):
        del season_id, episode_id
        for key in ("behavior_traits", "facts", "character_state_changes"):
            values = payload.get(key, [])
            if isinstance(values, list) and values:
                first = str(values[0]).split("：", 1)[0].split(":", 1)[0].strip()
                if first:
                    return first[:40]
    return "Preview Character"


def _related_items(value: object, character: str) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = character.strip().casefold()
    if not normalized:
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(item).strip() for item in value if normalized in str(item).casefold() and str(item).strip()]


def _build_system_prompt(card: CharacterCard) -> str:
    parts = [
        f"Role: {card.identity.display_name or card.identity.character_name}",
        card.profile.summary,
        card.profile.personality_traits and "Personality: " + "; ".join(card.profile.personality_traits),
        card.profile.speech_style and "Speech style: " + "; ".join(card.profile.speech_style),
        card.user_metadata.compile_requirements
        and "User requirements: " + card.user_metadata.compile_requirements,
    ]
    return "\n".join(str(item) for item in parts if item)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys([item.strip() for item in values if isinstance(item, str) and item.strip()]))
