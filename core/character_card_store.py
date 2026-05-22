from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from core import knowledge_base as kb
from core.models import (
    CharacterCard,
    CharacterCardCompileSource,
    CharacterCardKind,
    CharacterCardStatus,
    CharacterCardSummary,
)


LOGGER = logging.getLogger(__name__)
PREVIEW_CARD_ID = "preview_card"


def generate_card_id(character_name: str, *, existing_ids: set[str] | None = None) -> str:
    existing = existing_ids or set()
    base = _slugify(character_name) or "character"
    for _ in range(100):
        card_id = f"{base}-{uuid4().hex[:8]}"
        if card_id != PREVIEW_CARD_ID and card_id not in existing:
            return card_id
    raise RuntimeError("failed to generate unique character card id")


def create_empty_card(project_id: str, character_name: str = "") -> CharacterCard:
    name = character_name.strip() or "Untitled Character"
    card = CharacterCard(
        card_id=generate_card_id(name, existing_ids=_existing_card_ids(project_id)),
        project_id=project_id,
        card_kind=CharacterCardKind.OFFICIAL,
        compile_status=CharacterCardStatus.DRAFT,
        compile_source=CharacterCardCompileSource.MANUAL,
    )
    card.identity.character_name = name
    card.identity.display_name = name
    card.source_context.source_project_id = project_id
    return card


def create_preview_card(project_id: str, character_name: str = "") -> CharacterCard:
    name = character_name.strip() or "Preview Character"
    card = CharacterCard(
        card_id=PREVIEW_CARD_ID,
        project_id=project_id,
        card_kind=CharacterCardKind.PREVIEW,
        compile_status=CharacterCardStatus.PREVIEW,
        compile_source=CharacterCardCompileSource.PREVIEW,
    )
    card.identity.character_name = name
    card.identity.display_name = name
    card.source_context.source_project_id = project_id
    card.source_context.compiled_from_preview = True
    return card


def load_card(project_id: str, card_id: str) -> CharacterCard:
    return CharacterCard.model_validate(kb.read_json_object(kb.character_card_json_path(project_id, card_id)))


def save_card(card: CharacterCard) -> Path:
    if card.card_kind != CharacterCardKind.OFFICIAL:
        return save_preview_card(card)
    card.updated_at = datetime.now()
    return kb.write_json(
        kb.character_card_json_path(card.project_id, card.card_id),
        card.model_dump(mode="json"),
    )


def delete_card(project_id: str, card_id: str) -> None:
    card_dir = kb.character_card_dir_path(project_id, card_id).resolve()
    root = kb.character_cards_root_path(project_id).resolve()
    if card_dir == root or root not in card_dir.parents:
        raise ValueError(f"Unsafe character card path: {card_dir}")
    if card_dir.exists():
        shutil.rmtree(card_dir)


def list_card_summaries(project_id: str) -> list[CharacterCardSummary]:
    root = kb.character_cards_root_path(project_id)
    if not root.exists():
        return []
    summaries: list[CharacterCardSummary] = []
    for card_dir in sorted([path for path in root.iterdir() if path.is_dir()], key=lambda item: item.name.lower()):
        try:
            card = load_card(project_id, card_dir.name)
        except Exception:  # noqa: BLE001
            LOGGER.warning("Character card skipped; project_id=%s card_id=%s", project_id, card_dir.name, exc_info=True)
            continue
        if card.card_kind != CharacterCardKind.OFFICIAL:
            continue
        summaries.append(summary_from_card(card))
    return sorted(summaries, key=lambda item: item.updated_at, reverse=True)


def summary_from_card(card: CharacterCard) -> CharacterCardSummary:
    display_name = card.identity.display_name or card.identity.character_name or card.card_id
    cover_path = ""
    if card.assets.cover_path:
        cover_path = str(kb.character_card_dir_path(card.project_id, card.card_id) / card.assets.cover_path)
    return CharacterCardSummary(
        card_id=card.card_id,
        character_name=card.identity.character_name,
        display_name=display_name,
        aliases=card.identity.aliases,
        notes=card.user_metadata.notes,
        tags=card.user_metadata.tags,
        cover_path=cover_path,
        compile_status=card.compile_status,
        compile_source=card.compile_source,
        updated_at=card.updated_at,
        warnings=[*card.quality.warnings, *card.evidence.warnings],
    )


def load_preview_card(project_id: str) -> CharacterCard:
    return CharacterCard.model_validate(kb.read_json_object(kb.preview_character_card_json_path(project_id)))


def save_preview_card(card: CharacterCard) -> Path:
    card.card_id = PREVIEW_CARD_ID
    card.card_kind = CharacterCardKind.PREVIEW
    card.compile_status = CharacterCardStatus.PREVIEW
    card.compile_source = CharacterCardCompileSource.PREVIEW
    card.source_context.compiled_from_preview = True
    card.updated_at = datetime.now()
    return kb.write_json(
        kb.preview_character_card_json_path(card.project_id, PREVIEW_CARD_ID),
        card.model_dump(mode="json"),
    )


def mark_card_stale(card: CharacterCard, reason: str = "") -> CharacterCard:
    if card.compile_status == CharacterCardStatus.COMPILED:
        card.compile_status = CharacterCardStatus.STALE
        if reason:
            card.quality.warnings = [*card.quality.warnings, reason]
    card.updated_at = datetime.now()
    return card


def resolve_cover_paths(project_id: str, card_id: str, original_suffix: str = ".png") -> tuple[Path, Path]:
    card_dir = kb.character_card_dir_path(project_id, card_id)
    card_dir.mkdir(parents=True, exist_ok=True)
    suffix = original_suffix if original_suffix.startswith(".") else f".{original_suffix}"
    return card_dir / "cover.png", card_dir / f"original_cover{suffix.lower()}"


def clear_original_cover_reference(card: CharacterCard) -> CharacterCard:
    card.assets.original_cover_path = ""
    return card


def _existing_card_ids(project_id: str) -> set[str]:
    root = kb.character_cards_root_path(project_id)
    if not root.exists():
        return set()
    return {path.name for path in root.iterdir() if path.is_dir()}


def _slugify(value: str) -> str:
    output = []
    last_dash = False
    for char in value.strip().lower():
        if char.isalnum():
            output.append(char)
            last_dash = False
        elif not last_dash:
            output.append("-")
            last_dash = True
    slug = "".join(output).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:48].strip("-")
