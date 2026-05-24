from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core import character_card_store as store
from core import knowledge_base as kb
from core.models import (
    CharacterCard,
    CharacterCardCompileSource,
    CharacterCardKind,
    CharacterCardStatus,
)


class CharacterCardImportError(ValueError):
    pass


def load_charapicker_card_file(path: Path) -> CharacterCard:
    try:
        payload = kb.read_json_object(path)
    except Exception as exc:  # noqa: BLE001
        raise CharacterCardImportError(f"failed to read CharaPicker card: {path}") from exc
    return validate_charapicker_card_payload(payload)


def validate_charapicker_card_payload(payload: dict) -> CharacterCard:
    if payload.get("format") != "charapicker.card":
        raise CharacterCardImportError("not a CharaPicker card JSON")
    try:
        return CharacterCard.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise CharacterCardImportError("invalid CharaPicker card schema") from exc


def import_charapicker_card(project_id: str, path: Path) -> CharacterCard:
    source = load_charapicker_card_file(path)
    imported_card_id = source.card_id
    name = source.identity.character_name or source.identity.display_name or "Imported Character"
    source.card_id = store.generate_card_id(name, existing_ids={item.card_id for item in store.list_card_summaries(project_id)})
    source.project_id = project_id
    source.card_kind = CharacterCardKind.OFFICIAL
    source.compile_status = (
        CharacterCardStatus.DRAFT
        if source.compile_status == CharacterCardStatus.PREVIEW
        else source.compile_status
    )
    source.compile_source = CharacterCardCompileSource.IMPORTED_CHARAPICKER
    source.source_context.source_project_id = project_id
    source.source_context.imported_from_format = "charapicker.card"
    source.source_context.imported_card_id = imported_card_id
    source.source_context.imported_at = datetime.now().isoformat()
    source.source_context.compiled_from_preview = False
    source.created_at = datetime.now()
    source.updated_at = datetime.now()
    store.save_card(source)
    return source
