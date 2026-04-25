from __future__ import annotations

import logging

from core.models import CharacterState
from utils.i18n import t


LOGGER = logging.getLogger(__name__)


def compile_character_state(character: str) -> CharacterState:
    LOGGER.info("Character state compilation started; character=%s", character)
    return CharacterState(
        character=character,
        summary=t("compiler.placeholder.summary"),
    )
