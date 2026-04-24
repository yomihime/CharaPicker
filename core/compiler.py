from __future__ import annotations

from core.models import CharacterState


def compile_character_state(character: str) -> CharacterState:
    return CharacterState(
        character=character,
        summary="编译器占位实现: 后续会按 Retrieval -> Chunking -> Rolling Update 汇总角色状态。",
    )
