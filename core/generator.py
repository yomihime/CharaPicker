from __future__ import annotations

from core.models import CharacterState


def render_profile_markdown(state: CharacterState) -> str:
    return f"# {state.character}\n\n{state.summary}\n"
