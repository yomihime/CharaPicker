from __future__ import annotations

from dataclasses import dataclass, field

from core.models import CharacterCard, DialogueRole


@dataclass
class FormatPayload:
    payload: dict | list | str
    warnings: list[str] = field(default_factory=list)


def to_character_card_v2_json(card: CharacterCard) -> FormatPayload:
    warnings: list[str] = []
    name = card.identity.display_name or card.identity.character_name or card.card_id
    if card.timeline:
        warnings.append("timeline stored in extensions.charapicker")
    if card.evidence.refs:
        warnings.append("evidence refs stored in extensions.charapicker")
    data = {
        "name": name,
        "description": card.profile.long_description or card.profile.summary,
        "personality": card.profile.personality or "\n".join(card.profile.personality_traits),
        "scenario": card.prompt_surfaces.scenario or card.profile.scenario_default,
        "first_mes": card.prompt_surfaces.first_message or card.dialogue.first_message,
        "mes_example": card.prompt_surfaces.example_messages_text or _dialogues_text(card),
        "creator_notes": card.prompt_surfaces.creator_notes or card.user_metadata.notes,
        "system_prompt": card.prompt_surfaces.system_prompt,
        "post_history_instructions": card.prompt_surfaces.post_history_instructions,
        "alternate_greetings": card.prompt_surfaces.alternate_greetings or card.dialogue.alternate_greetings,
        "character_book": {
            "entries": [
                {
                    "keys": entry.keys,
                    "content": entry.content,
                    "enabled": entry.enabled,
                    "insertion_order": entry.insertion_order,
                }
                for entry in card.character_book.entries
            ]
        },
        "tags": card.user_metadata.tags,
        "creator": card.user_metadata.creator,
        "character_version": card.user_metadata.character_version,
        "extensions": {
            "charapicker": {
                "card_id": card.card_id,
                "schema_version": card.schema_version,
                "compile_status": card.compile_status.value,
                "source_context": card.source_context.model_dump(mode="json"),
                "timeline": card.timeline,
                "evidence": card.evidence.model_dump(mode="json"),
                "quality": card.quality.model_dump(mode="json"),
            }
        },
    }
    return FormatPayload(
        payload={
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": data,
        },
        warnings=warnings,
    )


def to_astrbot_copy_sections(card: CharacterCard) -> FormatPayload:
    name = _astrbot_persona_id(card)
    system_prompt = _astrbot_system_prompt(card)
    preset_dialogues, dialogue_warnings = _astrbot_dialogue_pairs(card)
    warnings = list(dialogue_warnings)
    if not system_prompt:
        warnings.append("system_prompt is empty")
    if not preset_dialogues:
        warnings.append("preset_dialogues is empty")
    return FormatPayload(
        payload={
            "name": name,
            "system_prompt": system_prompt,
            "custom_error_reply": card.prompt_surfaces.custom_error_reply,
            "preset_dialogues": preset_dialogues,
        },
        warnings=warnings,
    )


def to_astrbot_persona_json(card: CharacterCard) -> FormatPayload:
    sections = to_astrbot_copy_sections(card)
    payload = sections.payload if isinstance(sections.payload, dict) else {}
    begin_dialogs: list[str] = []
    for item in payload.get("preset_dialogues", []):
        if not isinstance(item, dict):
            continue
        user_text = str(item.get("user", "")).strip()
        assistant_text = str(item.get("assistant", "")).strip()
        if user_text and assistant_text:
            begin_dialogs.extend((user_text, assistant_text))
    return FormatPayload(
        payload={
            "persona_id": str(payload.get("name", "")),
            "system_prompt": str(payload.get("system_prompt", "")),
            "begin_dialogs": begin_dialogs,
        },
        warnings=list(sections.warnings),
    )


def to_astrbot_copy_markdown(card: CharacterCard) -> FormatPayload:
    sections = to_astrbot_copy_sections(card)
    payload = sections.payload if isinstance(sections.payload, dict) else {}
    lines = [
        "# AstrBot Copy Helper",
        "",
        "This supplemental helper is for fields not covered by the AstrBot persona import JSON.",
        "",
        "## Name",
        str(payload.get("name", "")),
        "",
        "## System Prompt",
        str(payload.get("system_prompt", "")),
        "",
        "## Custom Error Reply",
        str(payload.get("custom_error_reply", "")),
        "",
        "## Preset Dialogues",
    ]
    for index, item in enumerate(payload.get("preset_dialogues", []), start=1):
        lines.extend(
            [
                f"### Dialogue {index}",
                f"User: {item.get('user', '')}",
                f"Assistant: {item.get('assistant', '')}",
                "",
            ]
        )
    return FormatPayload(payload="\n".join(lines).rstrip() + "\n", warnings=sections.warnings)


def _dialogues_text(card: CharacterCard) -> str:
    chunks: list[str] = []
    for dialogue in card.dialogue.example_dialogues:
        for message in dialogue.messages:
            role = "User" if message.role == DialogueRole.USER else "Assistant"
            chunks.append(f"{role}: {message.content}")
    return "\n".join(chunks)


def _astrbot_persona_id(card: CharacterCard) -> str:
    for candidate in (card.identity.display_name, card.identity.character_name, card.card_id):
        name = candidate.strip()
        if name:
            return name[:255]
    return "character"


def _astrbot_system_prompt(card: CharacterCard) -> str:
    system_prompt = card.prompt_surfaces.system_prompt or card.prompt_surfaces.persona_prompt
    if not system_prompt:
        system_prompt = "\n".join(
            item
            for item in [
                card.profile.summary,
                card.profile.long_description,
                card.profile.personality,
                card.profile.speech_style and "Speech style: " + "; ".join(card.profile.speech_style),
            ]
            if item
        )
    extra_requirements = card.user_metadata.compile_requirements.strip()
    if extra_requirements and extra_requirements not in system_prompt:
        system_prompt = "\n\n".join(
            item
            for item in [
                system_prompt,
                "Additional user requirements:\n" + extra_requirements,
            ]
            if item
        )
    return system_prompt


def _astrbot_dialogue_pairs(card: CharacterCard) -> tuple[list[dict[str, str]], list[str]]:
    preset_dialogues: list[dict[str, str]] = []
    warnings: list[str] = []
    dialogues = card.dialogue.preset_dialogues or card.dialogue.example_dialogues
    for index, dialogue in enumerate(dialogues, start=1):
        user_text = ""
        assistant_text = ""
        for message in dialogue.messages:
            content = message.content.strip()
            if message.role == DialogueRole.USER and not user_text:
                user_text = content
            elif message.role == DialogueRole.ASSISTANT and not assistant_text:
                assistant_text = content
        if user_text and assistant_text:
            preset_dialogues.append(
                {
                    "title": dialogue.title,
                    "user": user_text,
                    "assistant": assistant_text,
                }
            )
        elif user_text or assistant_text:
            warnings.append(f"preset dialogue {index} skipped because one side is empty")
    if not preset_dialogues:
        assistant_text = (card.prompt_surfaces.first_message or card.dialogue.first_message).strip()
        starters = card.prompt_surfaces.suggested_starters or card.dialogue.suggested_starters
        starter_text = starters[0].strip() if starters else ""
        if assistant_text:
            preset_dialogues.append(
                {
                    "title": "Default Greeting",
                    "user": starter_text or "Please introduce yourself first.",
                    "assistant": assistant_text,
                }
            )
    return preset_dialogues, warnings
