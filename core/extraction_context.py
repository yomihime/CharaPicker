from __future__ import annotations

import json
from math import ceil
from typing import Any, Mapping


CONTEXT_TOKEN_ESTIMATE_MARGIN = 1.2


def build_episode_full_context_view(episode_content: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "season_id": _string_value(episode_content.get("season_id")),
        "episode_id": _string_value(episode_content.get("episode_id")),
        "episode_outline": _string_value(
            episode_content.get("episode_outline") or episode_content.get("insight_summary")
        ),
        "targets": _string_list(episode_content.get("targets")),
        "facts": _string_list(episode_content.get("facts")),
        "behavior_traits": _string_list(episode_content.get("behavior_traits")),
        "dialogue_style": _string_list(episode_content.get("dialogue_style")),
        "relationship_interactions": _string_list(episode_content.get("relationship_interactions")),
        "conflicts": _string_list(episode_content.get("conflicts")),
        "character_state_changes": _string_list(episode_content.get("character_state_changes")),
        "uncertainties": _string_list(episode_content.get("uncertainties")),
        "evidence_refs": _string_list(episode_content.get("evidence_refs")),
    }


def build_episode_context_long(
    episode_content: Mapping[str, Any],
    episode_summary: Mapping[str, Any] | None = None,
) -> str:
    summary = episode_summary or {}
    existing = _string_value(summary.get("context_long"))
    if existing:
        return existing

    sections = [
        ("概览", summary.get("insight_summary") or episode_content.get("insight_summary")),
        ("主要人物", summary.get("character_summaries") or episode_content.get("targets")),
        ("关键事件", summary.get("major_events") or episode_content.get("facts")),
        (
            "关系变化",
            summary.get("relationship_changes") or episode_content.get("relationship_interactions"),
        ),
        ("未解决冲突", summary.get("open_conflicts") or episode_content.get("conflicts")),
        (
            "状态变化",
            summary.get("growth_signals") or episode_content.get("character_state_changes"),
        ),
    ]
    return "\n".join(_format_context_section(title, value) for title, value in sections if value)


def build_episode_context_brief(
    episode_content: Mapping[str, Any],
    episode_summary: Mapping[str, Any] | None = None,
) -> str:
    summary = episode_summary or {}
    existing = _string_value(summary.get("context_brief"))
    if existing:
        return existing

    parts = [
        _string_value(summary.get("insight_summary") or episode_content.get("insight_summary")),
        _join_limited(summary.get("major_events") or episode_content.get("facts"), limit=3),
        _join_limited(summary.get("open_conflicts") or episode_content.get("conflicts"), limit=2),
    ]
    return " | ".join(part for part in parts if part)


def build_episode_context_candidate(
    episode_content: Mapping[str, Any],
    episode_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary = episode_summary or {}
    existing_candidate = summary.get("context_candidate")
    if isinstance(existing_candidate, dict):
        candidate = dict(existing_candidate)
    else:
        candidate = {}

    full_context_view = build_episode_full_context_view(episode_content)
    context_long = build_episode_context_long(episode_content, summary)
    context_brief = build_episode_context_brief(episode_content, summary)
    candidate.update(
        {
            "season_id": _string_value(episode_content.get("season_id")),
            "episode_id": _string_value(episode_content.get("episode_id")),
            "important_characters": _candidate_list(
                candidate.get("important_characters"),
                summary.get("character_summaries"),
                episode_content.get("targets"),
            ),
            "relationship_edges": _candidate_list(
                candidate.get("relationship_edges"),
                summary.get("relationship_changes"),
                episode_content.get("relationship_interactions"),
            ),
            "open_threads": _candidate_list(
                candidate.get("open_threads"),
                summary.get("open_conflicts"),
                episode_content.get("conflicts"),
            ),
            "continuity_hooks": _candidate_list(
                candidate.get("continuity_hooks"),
                summary.get("growth_signals"),
                episode_content.get("character_state_changes"),
            ),
            "locations": _candidate_list(candidate.get("locations")),
            "organizations": _candidate_list(candidate.get("organizations")),
            "importance_score": _importance_score(episode_content, summary, candidate),
            "estimated_context_tokens": {
                "full_context_view": estimate_context_tokens(full_context_view),
                "context_long": estimate_context_tokens(context_long),
                "context_brief": estimate_context_tokens(context_brief),
            },
        }
    )
    return candidate


def estimate_context_tokens(value: Any) -> int:
    if not isinstance(value, str):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = value
    if not text:
        return 0

    tokens = 0
    ascii_run = 0
    for char in text:
        if _is_cjk_or_kana(char):
            tokens += _flush_ascii_tokens(ascii_run)
            ascii_run = 0
            tokens += 1
        elif char.isspace():
            tokens += _flush_ascii_tokens(ascii_run)
            ascii_run = 0
        else:
            ascii_run += 1
    tokens += _flush_ascii_tokens(ascii_run)
    return int(ceil(tokens * CONTEXT_TOKEN_ESTIMATE_MARGIN))


def _candidate_list(*values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _string_list(value):
            if item not in seen:
                seen.add(item)
                output.append(item)
    return output


def _importance_score(
    episode_content: Mapping[str, Any],
    episode_summary: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> float:
    existing = candidate.get("importance_score")
    if isinstance(existing, (int, float)):
        return max(0.0, min(float(existing), 1.0))

    signal_count = (
        len(_string_list(episode_content.get("facts")))
        + len(_string_list(episode_content.get("conflicts"))) * 2
        + len(_string_list(episode_content.get("relationship_interactions"))) * 2
        + len(_string_list(episode_summary.get("open_conflicts"))) * 2
    )
    return max(0.0, min(signal_count / 20.0, 1.0))


def _format_context_section(title: str, value: Any) -> str:
    if isinstance(value, list):
        body = "；".join(_string_list(value))
    else:
        body = _string_value(value)
    return f"{title}：{body}" if body else ""


def _join_limited(value: Any, *, limit: int) -> str:
    items = _string_list(value)
    return "；".join(items[:limit])


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _is_cjk_or_kana(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3040 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _flush_ascii_tokens(length: int) -> int:
    if length <= 0:
        return 0
    return max(1, ceil(length / 4))
