"""Shared constants for CharaPicker character cards."""

PREVIEW_CARD_ID = "preview_card"
CHARACTER_CARD_JSON_FILE_NAME = "card.json"
CHARACTER_CARD_COVER_FILE_NAME = "cover.png"

STALE_WARNING_CHARACTER_NAME_CHANGED = "character_name_changed"
STALE_WARNING_COMPILE_INPUTS_CHANGED = "compile_inputs_changed"
STALE_WARNING_REASONS = frozenset(
    {
        STALE_WARNING_CHARACTER_NAME_CHANGED,
        STALE_WARNING_COMPILE_INPUTS_CHANGED,
    }
)
