from __future__ import annotations

from core.models import CharacterState
from utils.i18n import t


def compile_character_state(character: str) -> CharacterState:
    return CharacterState(
        character=character,
        summary=t("compiler.placeholder.summary"),
    )
