from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core import character_card_store as store
from core import knowledge_base as kb
from core.character_card_constants import STALE_WARNING_REASONS
from core.compiler import compile_character_state_by_season_episode
from core.models import (
    CharacterCard,
    CharacterCardBook,
    CharacterCardCompileSource,
    CharacterCardCompileTarget,
    CharacterCardCompileVariant,
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
CHARACTER_ALIAS_RESOLVE_PROMPT = "character_alias_resolve"
CHARACTER_CARD_COMPILE_TIMEOUT_SECONDS = 300
CHARACTER_ALIAS_RESOLVE_TIMEOUT_SECONDS = 120
JSON_CODE_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
EXPECTED_AI_RESPONSE_KEYS = (
    "profile",
    "prompt_surfaces",
    "dialogue",
    "character_book",
    "relationships",
    "warnings",
)
CompileStageCallback = Callable[[str], None]
StreamDeltaCallback = Callable[[str], None]

CHARAPICKER_EXTENSION_KEY = "charapicker"
DIRECT_EVIDENCE_FIELDS = (
    "facts",
    "behavior_traits",
    "dialogue_style",
    "character_state_changes",
)
MENTION_EVIDENCE_FIELDS = (
    "relationship_interactions",
    "relationships",
    "conflicts",
    "uncertainties",
    "insight_summary",
)
CONTEXT_CAUSAL_KEYWORDS = (
    "动机",
    "原因",
    "背景",
    "误解",
    "约束",
    "任务",
    "冲突",
    "影响",
    "cause",
    "motive",
    "reason",
    "background",
    "misunderstanding",
    "constraint",
    "conflict",
)
REVIEW_REASON_NO_DIRECT_EVIDENCE = "no_direct_evidence"
REVIEW_REASON_ALIAS_LOW_CONFIDENCE = "alias_resolution_low_confidence"
REVIEW_REASON_KNOWLEDGE_WARNINGS = "knowledge_base_has_warnings"
REVIEW_REASON_CONFLICT_REVIEW = "conflict_requires_review"
REVIEW_REASON_JSON_REPAIRED = "ai_json_repaired"


@dataclass
class AliasResolutionResult:
    aliases: list[str] = field(default_factory=list)
    confidence: str = "none"
    reason: str = ""
    source: str = "none"
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "matched_aliases": self.aliases,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class JsonParseResult:
    payload: dict[str, Any]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


def build_compile_target(card: CharacterCard) -> CharacterCardCompileTarget:
    character_name = card.identity.character_name.strip()
    if not character_name:
        raise ValueError("character name is required before compiling")
    return CharacterCardCompileTarget(
        project_id=card.project_id,
        card_id=card.card_id,
        character_name=character_name,
        compile_variant=card.user_metadata.compile_variant,
        compile_source=CharacterCardCompileSource.KNOWLEDGE_BASE,
    )


def compile_card_from_knowledge_base(
    card: CharacterCard,
    *,
    cloud_preset: CloudModelPreset | None = None,
    on_stage: CompileStageCallback | None = None,
    on_stream_delta: StreamDeltaCallback | None = None,
) -> CharacterCard:
    target = build_compile_target(card)
    _emit_stage(on_stage, "collecting")
    episode_payloads = _collect_episode_payloads(
        target.project_id,
        content_path=kb.episode_content_path,
        load_content=kb.load_episode_content,
        require_full=True,
    )
    if not episode_payloads:
        raise ValueError("formal knowledge base is not available")

    _emit_stage(on_stage, "local_compile")
    match_aliases = _card_match_terms(card)
    alias_resolution = AliasResolutionResult(source="local")
    evidence_layers = _build_compile_evidence_layers(
        target.project_id,
        match_aliases,
        episode_payloads,
    )
    if not _has_direct_evidence(evidence_layers) and cloud_preset is not None:
        _emit_stage(on_stage, "resolving_alias")
        alias_resolution = _resolve_character_aliases_with_ai(card, episode_payloads, cloud_preset)
        if alias_resolution.aliases:
            LOGGER.info(
                "Character card compile aliases resolved; project_id=%s card_id=%s character=%s aliases=%s",
                target.project_id,
                target.card_id,
                target.character_name,
                alias_resolution.aliases,
            )
            match_aliases = _unique([*match_aliases, *alias_resolution.aliases])
            evidence_layers = _build_compile_evidence_layers(
                target.project_id,
                match_aliases,
                episode_payloads,
            )
    if not _has_direct_evidence(evidence_layers):
        raise ValueError("character was not found in the formal knowledge base")

    compiled = compile_character_state_by_season_episode(
        target.project_id,
        target.character_name,
        aliases=match_aliases,
    )
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
    output.quality.last_error = ""
    output.quality.needs_review = False
    output.quality.warnings = []
    output.evidence.warnings = []
    _append_identity_aliases(output, alias_resolution.aliases)
    _write_compile_evidence_layers(output, evidence_layers)
    _write_quality_checks(output, {"alias_resolution": alias_resolution.to_payload()})
    _apply_compiled_state(output, final_state, timeline, episode_payloads)
    _emit_stage(on_stage, "ai_review")
    parse_diagnostics = _review_card_with_ai(
        output,
        final_state,
        timeline,
        episode_payloads,
        evidence_layers,
        cloud_preset,
        target.compile_variant,
        on_stage=on_stage,
        on_stream_delta=on_stream_delta,
    )
    _apply_quality_checks(
        output,
        evidence_layers,
        episode_payloads,
        match_aliases,
        alias_resolution,
        [*alias_resolution.diagnostics, *parse_diagnostics],
    )
    _record_last_compile_variant(output, target.compile_variant)
    _emit_stage(on_stage, "finalizing")
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
    warnings = [
        item
        for item in [*card.quality.warnings, *card.evidence.warnings]
        if item not in STALE_WARNING_REASONS
    ]
    if not card.profile.summary.strip():
        warnings.append("summary is empty")
    if card.evidence.evidence_count <= 0:
        warnings.append("no evidence was matched")
    return list(dict.fromkeys(warnings))


def _card_match_terms(card: CharacterCard) -> list[str]:
    identity = card.identity
    terms = [
        identity.character_name,
        identity.display_name,
        *identity.aliases,
        *identity.original_names,
        *identity.romanized_names,
    ]
    return _unique([str(term) for term in terms if str(term).strip()])


def _append_identity_aliases(card: CharacterCard, aliases: list[str]) -> None:
    if not aliases:
        return
    protected_names = {
        card.identity.character_name.strip().casefold(),
        card.identity.display_name.strip().casefold(),
    }
    existing = {item.strip().casefold() for item in card.identity.aliases}
    for alias in aliases:
        text = alias.strip()
        key = text.casefold()
        if not text or key in protected_names or key in existing:
            continue
        card.identity.aliases.append(text)
        existing.add(key)


def _resolve_character_aliases_with_ai(
    card: CharacterCard,
    episode_payloads: list[tuple[str, str, dict]],
    cloud_preset: CloudModelPreset,
) -> AliasResolutionResult:
    target_entries = _collect_target_entries(episode_payloads)
    if not target_entries:
        return AliasResolutionResult(source="none")
    request = build_model_call_request(
        purpose=CHARACTER_ALIAS_RESOLVE_PROMPT,
        backend=cloud_model_provider(cloud_preset.provider).backend_for("text"),
        model_name=cloud_preset.model_name,
        base_url=cloud_preset.base_url,
        api_key=cloud_preset.api_key,
        max_tokens=min(cloud_preset.max_output_tokens or 1024, 1024),
        variables={
            "character_identity": _build_alias_identity_payload(card),
            "existing_card_context": _build_alias_context_payload(card),
            "knowledge_targets": target_entries,
            "response_schema": {
                "matched_aliases": ["string copied from knowledge_targets"],
                "confidence": "high|medium|low|none",
                "reason": "string",
            },
        },
        metadata={
            "project_id": card.project_id,
            "card_id": card.card_id,
            "character": card.identity.character_name,
        },
    )
    request = request.model_copy(update={"timeout_seconds": CHARACTER_ALIAS_RESOLVE_TIMEOUT_SECONDS})
    try:
        result = call_text_model(request)
        parse_result = _parse_json_object_with_diagnostics(
            result.content,
            source=CHARACTER_ALIAS_RESOLVE_PROMPT,
        )
        payload = parse_result.payload
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            "Character alias resolution failed; project_id=%s card_id=%s character=%s",
            card.project_id,
            card.card_id,
            card.identity.character_name,
            exc_info=True,
        )
        return AliasResolutionResult(source="ai")
    aliases = payload.get("matched_aliases", [])
    if not isinstance(aliases, list):
        aliases = []
    confidence = str(payload.get("confidence") or "none").strip().lower()
    if confidence not in {"high", "medium", "low", "none"}:
        confidence = "none"
    return AliasResolutionResult(
        aliases=_validated_resolved_aliases(aliases, target_entries),
        confidence=confidence,
        reason=_clip_text(str(payload.get("reason") or ""), 500),
        source="ai",
        diagnostics=parse_result.diagnostics,
    )


def _build_alias_identity_payload(card: CharacterCard) -> dict[str, Any]:
    return {
        "character_name": card.identity.character_name,
        "display_name": card.identity.display_name,
        "aliases": card.identity.aliases,
        "original_names": card.identity.original_names,
        "romanized_names": card.identity.romanized_names,
        "source_work": card.identity.source_work,
        "role_titles": card.identity.role_titles,
        "species": card.identity.species,
    }


def _build_alias_context_payload(card: CharacterCard) -> dict[str, Any]:
    return {
        "summary": _clip_text(card.profile.summary, 800),
        "appearance": _clip_text(card.profile.appearance, 500),
        "personality": _clip_text(card.profile.personality, 500),
        "personality_traits": card.profile.personality_traits,
        "current_state": _clip_text(card.profile.current_state, 500),
        "notes": _clip_text(card.user_metadata.notes, 500),
        "tags": card.user_metadata.tags,
    }


def _collect_target_entries(
    episode_payloads: list[tuple[str, str, dict]],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for season_id, episode_id, payload in episode_payloads:
        targets = payload.get("targets", [])
        if not isinstance(targets, list):
            continue
        for item in targets:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "season_id": season_id,
                    "episode_id": episode_id,
                    "candidate_name": _target_candidate_name(text),
                    "target": _clip_text(text, 400),
                }
            )
    return entries[:120]


def _target_candidate_name(text: str) -> str:
    return re.split(r"[:：(<（]", text, maxsplit=1)[0].strip()


def _validated_resolved_aliases(
    aliases: list[object],
    target_entries: list[dict[str, str]],
) -> list[str]:
    target_texts = [
        f"{entry.get('candidate_name', '')} {entry.get('target', '')}".casefold()
        for entry in target_entries
    ]
    output: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        text = str(alias).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        if any(key in target_text for target_text in target_texts):
            output.append(text)
            seen.add(key)
    return output[:8]


def _emit_stage(callback: CompileStageCallback | None, stage: str) -> None:
    if callback is not None:
        callback(stage)


def _record_last_compile_variant(
    card: CharacterCard,
    compile_variant: CharacterCardCompileVariant,
) -> None:
    extension = _charapicker_extension(card)
    extension["last_compile_variant"] = compile_variant.value
    card.extensions[CHARAPICKER_EXTENSION_KEY] = extension


def _charapicker_extension(card: CharacterCard) -> dict[str, Any]:
    extension = card.extensions.get(CHARAPICKER_EXTENSION_KEY)
    return extension if isinstance(extension, dict) else {}


def _write_compile_evidence_layers(
    card: CharacterCard,
    evidence_layers: dict[str, list[dict[str, Any]]],
) -> None:
    extension = _charapicker_extension(card)
    extension["compile_evidence_layers"] = evidence_layers
    card.extensions[CHARAPICKER_EXTENSION_KEY] = extension


def _write_quality_checks(card: CharacterCard, updates: dict[str, Any]) -> None:
    extension = _charapicker_extension(card)
    quality_checks = extension.get("quality_checks")
    if not isinstance(quality_checks, dict):
        quality_checks = {}
    quality_checks.update(updates)
    extension["quality_checks"] = quality_checks
    card.extensions[CHARAPICKER_EXTENSION_KEY] = extension


def _build_compile_evidence_layers(
    project_id: str,
    match_terms: list[str],
    episode_payloads: list[tuple[str, str, dict]],
) -> dict[str, list[dict[str, Any]]]:
    direct_entries: list[dict[str, Any]] = []
    mention_entries: list[dict[str, Any]] = []
    causal_entries: list[dict[str, Any]] = []
    season_ids: list[str] = []

    for season_id, episode_id, payload in episode_payloads:
        season_ids.append(season_id)
        direct_items = _related_items_by_field(payload, match_terms, DIRECT_EVIDENCE_FIELDS)
        if direct_items:
            direct_entries.append(
                _evidence_entry(
                    season_id,
                    episode_id,
                    layer="direct",
                    match_terms=match_terms,
                    items_by_field=direct_items,
                    reason="matched character name or verified alias in episode evidence fields",
                    refs=_payload_refs(payload),
                    warnings=_payload_warnings(payload),
                )
            )
            continue

        mention_items = _related_items_by_field(payload, match_terms, MENTION_EVIDENCE_FIELDS)
        if _episode_targets_character(payload, match_terms):
            target_matches = _matching_targets(payload, match_terms)
            if target_matches:
                mention_items.setdefault("targets", target_matches)
        if mention_items:
            if _looks_causal_context(mention_items):
                causal_entries.append(
                    _evidence_entry(
                        season_id,
                        episode_id,
                        layer="causal",
                        match_terms=match_terms,
                        items_by_field=mention_items,
                        reason="matched contextual fields with causal or conflict language",
                        refs=_payload_refs(payload),
                        warnings=_payload_warnings(payload),
                    )
                )
            else:
                mention_entries.append(
                    _evidence_entry(
                        season_id,
                        episode_id,
                        layer="mention",
                        match_terms=match_terms,
                        items_by_field=mention_items,
                        reason="matched mention or target candidate without direct evidence",
                        refs=_payload_refs(payload),
                        warnings=_payload_warnings(payload),
                    )
                )

    return {
        "direct_evidence_episodes": direct_entries,
        "mention_evidence_episodes": mention_entries,
        "causal_context_episodes": causal_entries,
        "season_context": _build_season_context(project_id, _unique(season_ids), match_terms),
    }


def _has_direct_evidence(evidence_layers: dict[str, list[dict[str, Any]]]) -> bool:
    return bool(evidence_layers.get("direct_evidence_episodes"))


def _related_items_by_field(
    payload: dict,
    match_terms: list[str],
    fields: tuple[str, ...],
) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for field_name in fields:
        values = payload.get(field_name, [])
        if isinstance(values, str):
            values = [values]
        elif isinstance(values, dict):
            values = _flatten_text_values(values)
        related = _related_items(values, match_terms)
        if related:
            output[field_name] = related
    return output


def _flatten_text_values(value: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for item in value.values():
        if isinstance(item, str):
            output.append(item)
        elif isinstance(item, list):
            output.extend(str(entry) for entry in item if str(entry).strip())
        elif isinstance(item, dict):
            output.extend(_flatten_text_values(item))
    return output


def _evidence_entry(
    season_id: str,
    episode_id: str,
    *,
    layer: str,
    match_terms: list[str],
    items_by_field: dict[str, list[str]],
    reason: str,
    refs: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    source_fields = list(items_by_field.keys())
    evidence_items = [item for values in items_by_field.values() for item in values]
    return {
        "season_id": season_id,
        "episode_id": episode_id,
        "layer": layer,
        "match_terms": _matched_terms_in_values(evidence_items, match_terms),
        "classification_reason": reason,
        "source_fields": source_fields,
        "evidence_summary": _clip_text("; ".join(_compact_items(evidence_items, 6)), 900),
        "refs": refs,
        "warnings": warnings,
    }


def _matched_terms_in_values(values: list[str], match_terms: list[str]) -> list[str]:
    output: list[str] = []
    for term in match_terms:
        if any(_text_matches_term(value, term) for value in values):
            output.append(term)
    return _unique(output)


def _text_matches_term(value: str, term: str) -> bool:
    normalized_term = term.strip().casefold()
    return len(normalized_term) >= 2 and normalized_term in value.strip().casefold()


def _matching_targets(payload: dict, match_terms: list[str]) -> list[str]:
    targets = payload.get("targets", [])
    if not isinstance(targets, list):
        return []
    return [
        str(item).strip()
        for item in targets
        if str(item).strip() and any(_text_matches_term(str(item), term) for term in match_terms)
    ]


def _episode_targets_character(payload: dict, match_terms: list[str]) -> bool:
    return bool(_matching_targets(payload, match_terms))


def _text_matches_any_term(text: str, match_terms: list[str]) -> bool:
    return any(_text_matches_term(text, term) for term in match_terms)


def _looks_causal_context(items_by_field: dict[str, list[str]]) -> bool:
    text = " ".join(item for values in items_by_field.values() for item in values).casefold()
    return any(keyword.casefold() in text for keyword in CONTEXT_CAUSAL_KEYWORDS)


def _payload_refs(payload: dict) -> list[str]:
    return _compact_items([str(item) for item in payload.get("evidence_refs", [])], 20)


def _payload_warnings(payload: dict) -> list[str]:
    warnings = [str(item) for item in payload.get("aggregation_warnings", [])]
    source_counts = payload.get("source_counts", {})
    if isinstance(source_counts, dict):
        for key in ("skipped_chunks", "skipped_episodes", "skipped_seasons"):
            value = source_counts.get(key)
            if isinstance(value, int) and value > 0:
                warnings.append(f"{key}:{value}")
    return _unique(warnings)


def _build_season_context(
    project_id: str,
    season_ids: list[str],
    match_terms: list[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for season_id in season_ids:
        entry: dict[str, Any] = {"season_id": season_id, "warnings": []}
        summary = _load_full_season_summary(project_id, season_id)
        if summary:
            entry["season_summary"] = {
                "context_brief": _clip_text(str(summary.get("context_brief", "")), 1200),
                "context_long": _clip_text(str(summary.get("context_long", "")), 2400),
                "background_summary": _clip_text(str(summary.get("background_summary", "")), 1200),
                "series_background_summary": _clip_text(
                    str(summary.get("series_background_summary", "")),
                    1200,
                ),
                "final_character_states": _compact_items(
                    _related_items(summary.get("final_character_states", []), match_terms),
                    10,
                    max_chars=500,
                ),
                "major_conflicts": _compact_items(
                    _related_items(summary.get("major_conflicts", []), match_terms),
                    10,
                    max_chars=500,
                ),
                "unresolved_threads": _compact_items(
                    _related_items(summary.get("unresolved_threads", []), match_terms),
                    10,
                    max_chars=500,
                ),
            }
        stage_state = _character_stage_state_for_terms(project_id, season_id, match_terms)
        if stage_state:
            entry["character_stage_state"] = stage_state
        if "season_summary" in entry or "character_stage_state" in entry:
            output.append(entry)
    return output


def _load_full_season_summary(project_id: str, season_id: str) -> dict[str, Any] | None:
    path = kb.season_summary_path(project_id, season_id)
    if not path.exists():
        return None
    try:
        payload = kb.load_season_summary(project_id, season_id)
    except (OSError, ValueError, json.JSONDecodeError):
        LOGGER.warning(
            "Season summary skipped during card evidence layering; project_id=%s season_id=%s",
            project_id,
            season_id,
            exc_info=True,
        )
        return None
    return payload if kb.is_full_artifact_payload(payload) else None


def _character_stage_state_for_terms(
    project_id: str,
    season_id: str,
    match_terms: list[str],
) -> dict[str, Any] | None:
    try:
        payload = kb.load_character_stage_states(project_id, season_id)
    except (OSError, ValueError, json.JSONDecodeError):
        LOGGER.warning(
            "Character stage states skipped during card evidence layering; project_id=%s season_id=%s",
            project_id,
            season_id,
            exc_info=True,
        )
        return None
    characters = payload.get("characters", {})
    if not isinstance(characters, dict):
        return None
    for character, state_payload in characters.items():
        if not isinstance(character, str) or not _text_matches_any_term(character, match_terms):
            continue
        if not isinstance(state_payload, dict):
            continue
        final_state = state_payload.get("final_state", {})
        return {
            "character": character,
            "final_state": _compact_state_payload(final_state if isinstance(final_state, dict) else {}),
            "stage_count": len(state_payload.get("stage_states", []))
            if isinstance(state_payload.get("stage_states"), list)
            else 0,
        }
    return None


def _compact_state_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _clip_text(str(state.get("summary", "")), 1200),
        "evidence_count": state.get("evidence_count", 0),
        "conflicts": _compact_items([str(item) for item in state.get("conflicts", [])], 10),
    }


def _apply_quality_checks(
    card: CharacterCard,
    evidence_layers: dict[str, list[dict[str, Any]]],
    episode_payloads: list[tuple[str, str, dict]],
    match_terms: list[str],
    alias_resolution: AliasResolutionResult,
    parse_diagnostics: list[dict[str, Any]],
) -> None:
    conflict_groups = _build_conflict_groups(episode_payloads, match_terms)
    needs_review_reasons = _build_needs_review_reasons(
        evidence_layers,
        alias_resolution,
        conflict_groups,
        parse_diagnostics,
    )
    quality_checks = {
        "needs_review_reasons": needs_review_reasons,
        "conflict_groups": conflict_groups,
        "alias_resolution": alias_resolution.to_payload(),
        "parse_diagnostics": parse_diagnostics,
    }
    _write_quality_checks(card, quality_checks)

    reason_messages = [
        _review_reason_message(reason)
        for reason in needs_review_reasons
        if isinstance(reason, dict)
    ]
    card.quality.needs_review = bool(needs_review_reasons)
    card.quality.warnings = _unique([*card.quality.warnings, *reason_messages])
    card.evidence.warnings = collect_compile_warnings(card)


def _build_needs_review_reasons(
    evidence_layers: dict[str, list[dict[str, Any]]],
    alias_resolution: AliasResolutionResult,
    conflict_groups: list[dict[str, Any]],
    parse_diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if not _has_direct_evidence(evidence_layers):
        reasons.append(_review_reason(REVIEW_REASON_NO_DIRECT_EVIDENCE))
    if alias_resolution.source == "ai" and alias_resolution.confidence in {"low", "none"}:
        reasons.append(
            _review_reason(
                REVIEW_REASON_ALIAS_LOW_CONFIDENCE,
                detail=alias_resolution.reason,
            )
        )
    if _evidence_layers_have_warnings(evidence_layers):
        reasons.append(_review_reason(REVIEW_REASON_KNOWLEDGE_WARNINGS))
    if any(group.get("needs_review") for group in conflict_groups):
        reasons.append(_review_reason(REVIEW_REASON_CONFLICT_REVIEW))
    if parse_diagnostics:
        reasons.append(_review_reason(REVIEW_REASON_JSON_REPAIRED))
    return _unique_reason_payloads(reasons)


def _review_reason(reason: str, *, detail: str = "") -> dict[str, Any]:
    return {"reason": reason, "detail": _clip_text(detail, 500), "severity": "review"}


def _unique_reason_payloads(reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in reasons:
        key = str(item.get("reason", ""))
        if not key or key in seen:
            continue
        output.append(item)
        seen.add(key)
    return output


def _review_reason_message(reason: dict[str, Any]) -> str:
    key = str(reason.get("reason") or "")
    detail = str(reason.get("detail") or "").strip()
    return f"{key}: {detail}" if detail else key


def _evidence_layers_have_warnings(evidence_layers: dict[str, list[dict[str, Any]]]) -> bool:
    for entries in evidence_layers.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("warnings"):
                return True
    return False


def _build_conflict_groups(
    episode_payloads: list[tuple[str, str, dict]],
    match_terms: list[str],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for season_id, episode_id, payload in episode_payloads:
        conflicts = _related_items(payload.get("conflicts", []), match_terms)
        for conflict in conflicts:
            severity = "review" if _looks_dynamic_or_unresolved(conflict) else "info"
            groups.append(
                {
                    "description": _clip_text(conflict, 500),
                    "severity": severity,
                    "source_episodes": [f"{season_id}/{episode_id}"],
                    "candidate_explanations": _conflict_candidate_explanations(conflict),
                    "needs_review": severity != "info",
                }
            )
    return _deduplicate_conflict_groups(groups)


def _looks_dynamic_or_unresolved(text: str) -> bool:
    keywords = ("冲突", "矛盾", "不一致", "误解", "未确认", "复核", "uncertain", "conflict")
    normalized = text.casefold()
    return any(keyword in normalized for keyword in keywords)


def _conflict_candidate_explanations(text: str) -> list[str]:
    normalized = text.casefold()
    candidates: list[str] = []
    for label, keywords in {
        "misunderstanding": ("误解", "misunderstanding"),
        "relationship_shift": ("关系", "转折", "relationship"),
        "growth_or_change": ("成长", "变化", "黑化", "change"),
        "knowledge_inconsistency": ("矛盾", "不一致", "conflict", "inconsistent"),
    }.items():
        if any(keyword in normalized for keyword in keywords):
            candidates.append(label)
    return candidates or ["needs_human_review"]


def _deduplicate_conflict_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        key = str(group.get("description", "")).casefold()
        if not key or key in seen:
            continue
        output.append(group)
        seen.add(key)
    return output[:20]


def _apply_compiled_state(
    card: CharacterCard,
    final_state: dict,
    timeline: list[dict],
    episode_payloads: list[tuple[str, str, dict]],
) -> None:
    character = str(final_state.get("character") or card.identity.character_name or card.identity.display_name)
    match_terms = _card_match_terms(card)
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
        behavior.extend(_related_items(payload.get("behavior_traits", []), match_terms))
        speech.extend(_related_items(payload.get("dialogue_style", []), match_terms))
        for item in _related_items(payload.get("relationship_interactions", []), match_terms):
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
    evidence_layers: dict[str, list[dict[str, Any]]],
    cloud_preset: CloudModelPreset,
    compile_variant: CharacterCardCompileVariant,
    *,
    on_stage: CompileStageCallback | None = None,
    on_stream_delta: StreamDeltaCallback | None = None,
) -> list[dict[str, Any]]:
    request = build_model_call_request(
        purpose=CHARACTER_CARD_COMPILE_PROMPT,
        backend=cloud_model_provider(cloud_preset.provider).backend_for("text"),
        model_name=cloud_preset.model_name,
        base_url=cloud_preset.base_url,
        api_key=cloud_preset.api_key,
        max_tokens=cloud_preset.max_output_tokens,
        variables={
            "character": card.identity.character_name,
            "current_card": _build_ai_card_draft_payload(card),
            "knowledge_summary": _build_ai_knowledge_summary(card, final_state, timeline, episode_payloads),
            "evidence_layers": evidence_layers,
            "extra_requirements": _build_extra_requirements_prompt(card, compile_variant),
            "compile_variant": compile_variant.value,
            "compile_variant_instruction": _compile_variant_instruction(compile_variant),
            "extra_dialogue_count": _extra_dialogue_count_prompt_value(
                card.user_metadata.extra_dialogue_count
            ),
            "response_schema": _character_card_response_schema(compile_variant),
        },
        metadata={
            "project_id": card.project_id,
            "card_id": card.card_id,
            "character": card.identity.character_name,
        },
        stream=on_stream_delta is not None,
    )
    request = request.model_copy(update={"timeout_seconds": CHARACTER_CARD_COMPILE_TIMEOUT_SECONDS})
    result = call_text_model(request, on_stream_delta=on_stream_delta)
    _emit_stage(on_stage, "parsing")
    parse_result = _parse_json_object_with_diagnostics(
        result.content,
        source=CHARACTER_CARD_COMPILE_PROMPT,
    )
    payload = parse_result.payload
    _apply_ai_card_payload(card, payload)
    card.source_context.prompt_profile_id = CHARACTER_CARD_COMPILE_PROMPT
    card.source_context.model_profile_id = cloud_preset.name
    return parse_result.diagnostics


def _build_ai_knowledge_summary(
    card: CharacterCard,
    final_state: dict,
    timeline: list[dict],
    episode_payloads: list[tuple[str, str, dict]],
) -> dict[str, Any]:
    match_terms = _card_match_terms(card)
    episodes: list[dict[str, Any]] = []
    for season_id, episode_id, payload in episode_payloads:
        episodes.append(
            {
                "season_id": season_id,
                "episode_id": episode_id,
                "facts": _compact_items(_related_items(payload.get("facts", []), match_terms), 24),
                "behavior_traits": _compact_items(
                    _related_items(payload.get("behavior_traits", []), match_terms),
                    24,
                ),
                "dialogue_style": _compact_items(
                    _related_items(payload.get("dialogue_style", []), match_terms),
                    16,
                ),
                "relationships": _compact_items(
                    _related_items(
                        payload.get("relationship_interactions", payload.get("relationships", [])),
                        match_terms,
                    ),
                    16,
                ),
                "state_changes": _compact_items(
                    _related_items(payload.get("character_state_changes", []), match_terms),
                    16,
                ),
                "conflicts": _compact_items(_related_items(payload.get("conflicts", []), match_terms), 12),
                "insight_summary": _clip_text(str(payload.get("insight_summary", "")), 500),
                "evidence_refs": _compact_items(
                    [str(item) for item in payload.get("evidence_refs", []) if str(item).strip()],
                    20,
                ),
            }
        )
    return {
        "final_state": {
            "character": final_state.get("character", ""),
            "summary": _clip_text(str(final_state.get("summary", "")), 4000),
            "evidence_count": final_state.get("evidence_count", 0),
            "conflicts": _compact_items([str(item) for item in final_state.get("conflicts", [])], 20),
        },
        "timeline": _compact_timeline(timeline),
        "episodes": episodes,
    }


def _build_ai_card_draft_payload(card: CharacterCard) -> dict[str, Any]:
    return {
        "identity": card.identity.model_dump(mode="json"),
        "user_metadata": {
            "notes": _clip_text(card.user_metadata.notes, 1200),
            "compile_requirements": _clip_text(card.user_metadata.compile_requirements, 1200),
            "compile_variant": card.user_metadata.compile_variant.value,
            "extra_dialogue_count": card.user_metadata.extra_dialogue_count,
            "tags": card.user_metadata.tags,
        },
        "profile": {
            "summary": _clip_text(card.profile.summary, 2000),
            "personality_traits": card.profile.personality_traits,
            "speech_style": card.profile.speech_style,
            "current_state": _clip_text(card.profile.current_state, 2000),
        },
        "prompt_surfaces": {
            "system_prompt": _clip_text(card.prompt_surfaces.system_prompt, 2000),
            "persona_prompt": _clip_text(card.prompt_surfaces.persona_prompt, 2000),
            "scenario": _clip_text(card.prompt_surfaces.scenario, 1200),
        },
        "evidence": card.evidence.model_dump(mode="json"),
    }


def _compact_timeline(timeline: list[dict]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        state = item.get("state", {})
        if not isinstance(state, dict):
            state = {}
        output.append(
            {
                "season_id": item.get("season_id", ""),
                "episode_id": item.get("episode_id", ""),
                "state": {
                    "character": state.get("character", ""),
                    "summary": _clip_text(str(state.get("summary", "")), 1200),
                    "evidence_count": state.get("evidence_count", 0),
                    "conflicts": _compact_items([str(value) for value in state.get("conflicts", [])], 8),
                },
            }
        )
    return output


def _compact_items(values: list[str], limit: int, *, max_chars: int = 500) -> list[str]:
    return [_clip_text(value, max_chars) for value in _unique(values)[:limit]]


def _clip_text(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _character_card_response_schema(compile_variant: CharacterCardCompileVariant) -> dict[str, Any]:
    if compile_variant == CharacterCardCompileVariant.ASTRBOT:
        return {
            "prompt_surfaces": {
                "system_prompt": "string",
                "custom_error_reply": "string",
                "suggested_starters": ["string"],
                "creator_notes": "string",
            },
            "dialogue": {
                "preset_dialogues": [
                    {
                        "title": "string",
                        "messages": [{"role": "user|assistant", "content": "string"}],
                    }
                ]
            },
            "warnings": ["string"],
        }
    if compile_variant == CharacterCardCompileVariant.CHARACTER_CARD_V2:
        return {
            "profile": {
                "long_description": "string",
                "personality": "string",
                "scenario_default": "string",
                "creator_notes": "string",
            },
            "prompt_surfaces": {
                "first_message": "string",
                "example_messages_text": "string",
                "creator_notes": "string",
            },
            "dialogue": {
                "first_message": "string",
                "example_dialogues": [
                    {
                        "title": "string",
                        "messages": [{"role": "user|assistant", "content": "string"}],
                    }
                ],
            },
            "character_book": {
                "entries": [{"keys": ["string"], "content": "string", "enabled": True, "insertion_order": 100}]
            },
            "warnings": ["string"],
        }
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
            "example_dialogues": [
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
    _enforce_extra_dialogue_count(card)


def _build_extra_requirements_prompt(
    card: CharacterCard,
    compile_variant: CharacterCardCompileVariant,
) -> str:
    requirements = card.user_metadata.compile_requirements.strip()
    parts = [
        _compile_variant_instruction(compile_variant),
        _extra_dialogue_count_instruction(card.user_metadata.extra_dialogue_count),
    ]
    if requirements:
        parts.insert(0, requirements)
    return "\n\n".join(part for part in parts if part.strip())


def _compile_variant_instruction(compile_variant: CharacterCardCompileVariant) -> str:
    if compile_variant == CharacterCardCompileVariant.ASTRBOT:
        return (
            "Compile target: AstrBot manual copy only. For this run, write only the AstrBot-facing "
            "surface: prompt_surfaces.system_prompt, prompt_surfaces.custom_error_reply, "
            "dialogue.preset_dialogues, and any directly needed suggested starters. Do not spend "
            "output budget rewriting general profile text or Character Card V2 fields unless needed "
            "to keep the returned JSON valid. CharaPicker JSON remains the source of truth; AstrBot "
            "text is a derived target surface."
        )
    if compile_variant == CharacterCardCompileVariant.CHARACTER_CARD_V2:
        return (
            "Compile target: Character Card V2 only. For this run, write only the fields needed for "
            "a clean V2 export: profile.long_description, profile.personality, "
            "profile.scenario_default, prompt_surfaces.first_message, "
            "prompt_surfaces.example_messages_text, and dialogue.example_dialogues. Do not spend "
            "output budget rewriting AstrBot-specific fields or unrelated general profile fields "
            "unless needed to keep the returned JSON valid. CharaPicker JSON remains the source of "
            "truth; V2 JSON is a derived target surface."
        )
    return (
        "Compile target: general CharaPicker card only. For this run, write the general profile, "
        "prompt surfaces, dialogue examples, character book entries, and warnings needed by the "
        "native CharaPicker card. Do not specialize the output for AstrBot or Character Card V2."
    )


def _extra_dialogue_count_prompt_value(value: int | None) -> str:
    return "auto" if value is None else str(value)


def _extra_dialogue_count_instruction(value: int | None) -> str:
    if value is None:
        return (
            "Extra dialogue sample count: auto. Let the model choose an appropriate number of "
            "dialogue sample groups based on available evidence, user requirements, and output budget."
        )
    if value == 0:
        return (
            "Extra dialogue sample count: 0. Do not generate dialogue sample groups; return empty "
            "dialogue.preset_dialogues and dialogue.example_dialogues."
        )
    return (
        f"Extra dialogue sample count: {value}. Generate exactly {value} dialogue sample group(s) "
        "in dialogue.preset_dialogues. Each group should contain at least one user message and one "
        "assistant reply. Also mirror the same groups in dialogue.example_dialogues when useful for "
        "Character Card V2 export. Keep every group grounded in the formal knowledge base evidence "
        "and the user's extra requirements."
    )


def _enforce_extra_dialogue_count(card: CharacterCard) -> None:
    requested_count = card.user_metadata.extra_dialogue_count
    if requested_count is None:
        return
    if requested_count == 0:
        card.dialogue.preset_dialogues = []
        card.dialogue.example_dialogues = []
        return

    preset_dialogues = _usable_dialogues(card.dialogue.preset_dialogues)
    example_dialogues = _usable_dialogues(card.dialogue.example_dialogues)
    if len(preset_dialogues) < requested_count:
        preset_dialogues.extend(
            dialogue.model_copy(deep=True)
            for dialogue in example_dialogues
            if len(preset_dialogues) < requested_count
        )
    if len(example_dialogues) < requested_count:
        example_dialogues.extend(
            dialogue.model_copy(deep=True)
            for dialogue in preset_dialogues
            if len(example_dialogues) < requested_count
        )
    card.dialogue.preset_dialogues = preset_dialogues[:requested_count]
    card.dialogue.example_dialogues = example_dialogues[:requested_count]
    actual_count = len(card.dialogue.preset_dialogues)
    if actual_count < requested_count:
        warning = (
            f"requested {requested_count} dialogue sample group(s), "
            f"but the model returned {actual_count}"
        )
        card.quality.warnings = _unique([*card.quality.warnings, warning])
        card.evidence.warnings = collect_compile_warnings(card)


def _usable_dialogues(dialogues: list[Any]) -> list[Any]:
    return [dialogue for dialogue in dialogues if getattr(dialogue, "messages", None)]


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
    return _parse_json_object_with_diagnostics(text).payload


def _parse_json_object_with_diagnostics(
    text: str,
    *,
    source: str = "",
) -> JsonParseResult:
    payloads: list[tuple[tuple[int, int, int], dict[str, Any], list[dict[str, Any]]]] = []
    last_error: json.JSONDecodeError | None = None
    for candidate, candidate_diagnostics in _iter_json_candidate_texts(text, source=source):
        candidate_payloads, error = _parse_json_candidate_payloads(candidate, source=source)
        payloads.extend(
            (score, payload, [*candidate_diagnostics, *diagnostics])
            for score, payload, diagnostics in candidate_payloads
        )
        if error is not None:
            last_error = error
    if payloads:
        _score, payload, diagnostics = max(payloads, key=lambda item: item[0])
        return JsonParseResult(payload=payload, diagnostics=_unique_diagnostics(diagnostics))
    if "{" not in text or "}" not in text:
        raise ValueError("character card model response did not contain a JSON object")
    detail = ""
    if last_error is not None:
        detail = f": {last_error.msg} at line {last_error.lineno} column {last_error.colno}"
    raise ValueError(f"character card model response was not valid JSON{detail}") from last_error


def _iter_json_candidate_texts(
    text: str,
    *,
    source: str,
) -> list[tuple[str, list[dict[str, Any]]]]:
    stripped = text.strip().lstrip("\ufeff")
    candidates = [
        (
            match.group(1).strip(),
            [_parse_diagnostic(source, "code_block", "extracted JSON from a code block")],
        )
        for match in JSON_CODE_BLOCK_PATTERN.finditer(stripped)
    ]
    candidates.append((stripped, []))
    return [(candidate, diagnostics) for candidate, diagnostics in candidates if candidate]


def _parse_json_candidate_payloads(
    candidate: str,
    *,
    source: str,
) -> tuple[
    list[tuple[tuple[int, int, int], dict[str, Any], list[dict[str, Any]]]],
    json.JSONDecodeError | None,
]:
    payloads: list[tuple[tuple[int, int, int], dict[str, Any], list[dict[str, Any]]]] = []
    last_error: json.JSONDecodeError | None = None
    variants: list[tuple[str, list[dict[str, Any]]]] = [(_strip_json_language_prefix(candidate), [])]
    without_trailing_commas = _remove_trailing_json_commas(variants[0][0])
    if without_trailing_commas != variants[0][0]:
        variants.append(
            (
                without_trailing_commas,
                [_parse_diagnostic(source, "trailing_comma", "removed trailing JSON commas")],
            )
        )

    for variant, variant_diagnostics in variants:
        stripped = variant.strip()
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            last_error = exc
        else:
            if isinstance(payload, dict):
                payloads.append(
                    (
                        _json_payload_score(payload, 0, len(stripped)),
                        payload,
                        variant_diagnostics,
                    )
                )

        decoder = json.JSONDecoder()
        for match in re.finditer(r"{", stripped):
            start = match.start()
            try:
                payload, end = decoder.raw_decode(stripped[start:])
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(payload, dict):
                diagnostics = list(variant_diagnostics)
                if start > 0 or end < len(stripped):
                    diagnostics.append(
                        _parse_diagnostic(source, "embedded_json", "decoded JSON object from surrounding text")
                    )
                payloads.append((_json_payload_score(payload, start, end), payload, diagnostics))
    return payloads, last_error


def _parse_diagnostic(source: str, repair: str, message: str) -> dict[str, Any]:
    return {
        "source": source or CHARACTER_CARD_COMPILE_PROMPT,
        "repair": repair,
        "needs_review": True,
        "message": message,
    }


def _unique_diagnostics(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in diagnostics:
        source = str(item.get("source") or "")
        repair = str(item.get("repair") or "")
        key = (source, repair)
        if not repair or key in seen:
            continue
        output.append(item)
        seen.add(key)
    return output


def _strip_json_language_prefix(text: str) -> str:
    stripped = text.strip()
    if stripped.lower().startswith("json\n"):
        return stripped[5:].lstrip()
    if stripped.lower().startswith("json\r\n"):
        return stripped[6:].lstrip()
    return stripped


def _remove_trailing_json_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _json_payload_score(payload: dict[str, Any], start: int, span: int) -> tuple[int, int, int]:
    expected_key_count = sum(1 for key in EXPECTED_AI_RESPONSE_KEYS if key in payload)
    return (expected_key_count, -start, span)


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


def _related_items(value: object, character: str | list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    match_terms = character if isinstance(character, list) else [character]
    normalized_terms = [
        term.strip().casefold()
        for term in match_terms
        if isinstance(term, str) and len(term.strip()) >= 2
    ]
    if not normalized_terms:
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        str(item).strip()
        for item in value
        if str(item).strip()
        and any(term in str(item).casefold() for term in normalized_terms)
    ]


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
