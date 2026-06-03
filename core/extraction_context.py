from __future__ import annotations

import json
from math import ceil
from typing import Any, Mapping


CONTEXT_TOKEN_ESTIMATE_MARGIN = 1.2
DEFAULT_EPISODE_CONTEXT_BUDGET_TOKENS = 128000
STRONG_RELEVANCE_THRESHOLD = 0.65
MEDIUM_RELEVANCE_THRESHOLD = 0.35


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
            "full_context_view": full_context_view,
            "context_long": context_long,
            "context_brief": context_brief,
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


def build_current_signals(
    *,
    current_episode_chunks: list[Mapping[str, Any]] | None = None,
    previous_episode_summary: Mapping[str, Any] | None = None,
    season_rolling_context: Mapping[str, Any] | None = None,
    previous_season_summary: Mapping[str, Any] | None = None,
    episode_title: str = "",
) -> dict[str, Any]:
    chunks = current_episode_chunks or []
    signals = {
        "episode_title": episode_title,
        "characters": [],
        "relationship_edges": [],
        "open_threads": [],
        "continuity_hooks": [],
        "locations": [],
        "organizations": [],
        "keywords": [],
    }
    for chunk in chunks:
        signals["characters"].extend(_string_list(chunk.get("targets")))
        signals["relationship_edges"].extend(_string_list(chunk.get("relationship_interactions")))
        signals["open_threads"].extend(_string_list(chunk.get("conflicts")))
        signals["continuity_hooks"].extend(_string_list(chunk.get("character_state_changes")))
        signals["keywords"].extend(_string_list(chunk.get("facts")))

    for source in (previous_episode_summary, season_rolling_context, previous_season_summary):
        if not source:
            continue
        signals["open_threads"].extend(_string_list(source.get("open_conflicts")))
        signals["continuity_hooks"].extend(_string_list(source.get("growth_signals")))
        signals["keywords"].extend(_string_list(source.get("background_summary")))

    return {key: _candidate_list(value) if isinstance(value, list) else value for key, value in signals.items()}


def score_episode_context_candidate(
    candidate: Mapping[str, Any],
    current_signals: Mapping[str, Any],
    *,
    episode_distance: int = 0,
    is_previous_episode: bool = False,
) -> dict[str, Any]:
    recency_score = _recency_score(episode_distance)
    character_overlap_score = _overlap_score(
        candidate.get("important_characters"),
        current_signals.get("characters"),
    )
    thread_overlap_score = _overlap_score(
        candidate.get("open_threads"),
        current_signals.get("open_threads"),
    )
    relationship_overlap_score = _overlap_score(
        candidate.get("relationship_edges"),
        current_signals.get("relationship_edges"),
    )
    location_or_org_overlap_score = max(
        _overlap_score(candidate.get("locations"), current_signals.get("locations")),
        _overlap_score(candidate.get("organizations"), current_signals.get("organizations")),
    )
    importance_score = _bounded_float(candidate.get("importance_score"), default=0.0)
    previous_episode_bonus = 0.15 if is_previous_episode else 0.0
    relevance = (
        0.25 * recency_score
        + 0.30 * character_overlap_score
        + 0.20 * thread_overlap_score
        + 0.10 * relationship_overlap_score
        + 0.05 * location_or_org_overlap_score
        + 0.10 * importance_score
        + previous_episode_bonus
    )
    relevance = max(0.0, min(relevance, 1.0))
    return {
        "relevance": relevance,
        "recency_score": recency_score,
        "character_overlap_score": character_overlap_score,
        "thread_overlap_score": thread_overlap_score,
        "relationship_overlap_score": relationship_overlap_score,
        "location_or_org_overlap_score": location_or_org_overlap_score,
        "importance_score": importance_score,
        "previous_episode_bonus": previous_episode_bonus,
    }


def select_episode_context_candidates(
    candidates: list[Mapping[str, Any]],
    current_signals: Mapping[str, Any],
    *,
    episode_context_budget_tokens: int = DEFAULT_EPISODE_CONTEXT_BUDGET_TOKENS,
    previous_episode_id: str = "",
) -> dict[str, Any]:
    scored_candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        episode_id = _string_value(candidate.get("episode_id"))
        is_previous_episode = bool(previous_episode_id and episode_id == previous_episode_id)
        score = score_episode_context_candidate(
            candidate,
            current_signals,
            episode_distance=max(len(candidates) - index, 0),
            is_previous_episode=is_previous_episode,
        )
        scored_candidates.append(
            {
                "candidate": candidate,
                "score": score,
                "is_previous_episode": is_previous_episode,
            }
        )

    selected: list[dict[str, Any]] = []
    used_tokens = 0
    for item in sorted(scored_candidates, key=_candidate_sort_key, reverse=True):
        candidate = item["candidate"]
        score = item["score"]
        view = _initial_context_view(score["relevance"], item["is_previous_episode"])
        cost = _candidate_view_cost(candidate, view)
        if cost <= 0:
            continue
        while used_tokens + cost > episode_context_budget_tokens and view != "context_brief":
            view = _downgrade_context_view(view)
            cost = _candidate_view_cost(candidate, view)
        if used_tokens + cost > episode_context_budget_tokens:
            continue
        used_tokens += cost
        selected.append(
            {
                "season_id": _string_value(candidate.get("season_id")),
                "episode_id": _string_value(candidate.get("episode_id")),
                "view": view,
                "estimated_tokens": cost,
                "relevance": score["relevance"],
                "selection_reason": _selection_reason(score["relevance"], item["is_previous_episode"]),
            }
        )

    return {
        "selected_contexts": selected,
        "context_policy": {
            "episode_context_budget_tokens": episode_context_budget_tokens,
            "used_tokens": used_tokens,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "candidates": [
                {
                    "season_id": _string_value(item["candidate"].get("season_id")),
                    "episode_id": _string_value(item["candidate"].get("episode_id")),
                    **item["score"],
                }
                for item in scored_candidates
            ],
        },
    }


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


def _candidate_sort_key(item: Mapping[str, Any]) -> tuple[float, float]:
    score = item["score"]
    candidate = item["candidate"]
    best_cost = max(_candidate_view_cost(candidate, "context_brief"), 1)
    value_per_token = score["relevance"] / best_cost
    previous_bonus = 1.0 if item["is_previous_episode"] else 0.0
    return (previous_bonus, value_per_token + score["relevance"])


def _initial_context_view(relevance: float, is_previous_episode: bool) -> str:
    if is_previous_episode or relevance >= STRONG_RELEVANCE_THRESHOLD:
        return "full_context_view"
    if relevance >= MEDIUM_RELEVANCE_THRESHOLD:
        return "context_long"
    return "context_brief"


def _downgrade_context_view(view: str) -> str:
    if view == "full_context_view":
        return "context_long"
    return "context_brief"


def _candidate_view_cost(candidate: Mapping[str, Any], view: str) -> int:
    costs = candidate.get("estimated_context_tokens")
    if not isinstance(costs, dict):
        return 0
    value = costs.get(view)
    return value if isinstance(value, int) and value > 0 else 0


def _selection_reason(relevance: float, is_previous_episode: bool) -> str:
    if is_previous_episode:
        return "previous_episode_priority"
    if relevance >= STRONG_RELEVANCE_THRESHOLD:
        return "strong_relevance"
    if relevance >= MEDIUM_RELEVANCE_THRESHOLD:
        return "medium_relevance"
    return "low_cost_background"


def _recency_score(episode_distance: int) -> float:
    if episode_distance <= 0:
        return 1.0
    return 1.0 / (1.0 + float(episode_distance))


def _overlap_score(left: Any, right: Any) -> float:
    left_items = {_normalize_match_key(item) for item in _string_list(left)}
    right_items = {_normalize_match_key(item) for item in _string_list(right)}
    left_items.discard("")
    right_items.discard("")
    if not left_items or not right_items:
        return 0.0
    return len(left_items & right_items) / max(len(left_items), len(right_items), 1)


def _bounded_float(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    return default


def _normalize_match_key(value: str) -> str:
    return value.strip().lower().replace("＿", "_").replace(" ", "")


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
