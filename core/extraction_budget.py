from __future__ import annotations

from dataclasses import dataclass


FORMAL_CONTEXTUAL_VIDEO_CHUNK_EXTRACTION = "formal_contextual_video_chunk_extraction"
FORMAL_EPISODE_CONTENT_MERGE = "formal_episode_content_merge"
FORMAL_EPISODE_SUMMARY = "formal_episode_summary"
FORMAL_SEASON_CONTENT_MERGE = "formal_season_content_merge"
FORMAL_SEASON_SUMMARY = "formal_season_summary"


@dataclass(frozen=True, slots=True)
class TextMergeOutputBudget:
    min_tokens: int
    target_tokens: int
    max_tokens: int
    per_source_item_tokens: int = 0
    input_token_divisor: int = 0


TEXT_MERGE_OUTPUT_BUDGETS: dict[str, TextMergeOutputBudget] = {
    FORMAL_EPISODE_CONTENT_MERGE: TextMergeOutputBudget(
        min_tokens=2048,
        target_tokens=4096,
        max_tokens=16384,
        per_source_item_tokens=512,
        input_token_divisor=8,
    ),
    FORMAL_EPISODE_SUMMARY: TextMergeOutputBudget(
        min_tokens=1024,
        target_tokens=2048,
        max_tokens=8192,
        per_source_item_tokens=128,
        input_token_divisor=16,
    ),
    FORMAL_SEASON_CONTENT_MERGE: TextMergeOutputBudget(
        min_tokens=4096,
        target_tokens=8192,
        max_tokens=32768,
        per_source_item_tokens=1024,
        input_token_divisor=8,
    ),
    FORMAL_SEASON_SUMMARY: TextMergeOutputBudget(
        min_tokens=2048,
        target_tokens=4096,
        max_tokens=16384,
        per_source_item_tokens=256,
        input_token_divisor=16,
    ),
}


def resolve_text_merge_output_tokens(
    purpose: str,
    *,
    source_item_count: int = 0,
    estimated_input_tokens: int = 0,
    context_window_tokens: int | None = None,
    reserved_input_tokens: int = 0,
    safety_margin_tokens: int = 1024,
) -> int:
    budget = TEXT_MERGE_OUTPUT_BUDGETS.get(purpose)
    if budget is None:
        raise ValueError(f"unknown text merge output budget purpose: {purpose}")

    requested_tokens = budget.target_tokens
    if source_item_count > 1:
        requested_tokens += (source_item_count - 1) * budget.per_source_item_tokens
    if budget.input_token_divisor > 0 and estimated_input_tokens > 0:
        requested_tokens += estimated_input_tokens // budget.input_token_divisor

    requested_tokens = min(max(requested_tokens, budget.min_tokens), budget.max_tokens)
    if context_window_tokens is None or context_window_tokens <= 0:
        return requested_tokens

    available_output_tokens = context_window_tokens - reserved_input_tokens - safety_margin_tokens
    if available_output_tokens < budget.min_tokens:
        return budget.min_tokens
    return min(requested_tokens, available_output_tokens, budget.max_tokens)


def text_merge_budget_warning(
    purpose: str,
    *,
    requested_output_tokens: int,
    context_window_tokens: int | None,
    reserved_input_tokens: int = 0,
    safety_margin_tokens: int = 1024,
) -> str:
    budget = TEXT_MERGE_OUTPUT_BUDGETS.get(purpose)
    if budget is None or context_window_tokens is None or context_window_tokens <= 0:
        return ""

    available_output_tokens = context_window_tokens - reserved_input_tokens - safety_margin_tokens
    if available_output_tokens >= budget.min_tokens:
        return ""
    return (
        "text_merge_output_budget_below_minimum:"
        f"purpose={purpose},requested={requested_output_tokens},"
        f"available={available_output_tokens},minimum={budget.min_tokens}"
    )
