from __future__ import annotations

import logging

from core.models import CharacterState


LOGGER = logging.getLogger(__name__)


def render_profile_markdown(state: CharacterState) -> str:
    LOGGER.debug(
        "Rendering profile markdown; character=%s evidence_count=%s conflicts=%s",
        state.character,
        state.evidence_count,
        len(state.conflicts),
    )
    return f"# {state.character}\n\n{state.summary}\n"
