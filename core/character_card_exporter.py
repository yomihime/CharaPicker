from __future__ import annotations

import json
from pathlib import Path

from core.character_card_formats import (
    to_astrbot_copy_markdown,
    to_character_card_v2_json,
)
from core.character_card_renderers import render_card_html, render_card_markdown
from core.models import (
    CharacterCard,
    CharacterCardExportResult,
    CharacterCardExportStatus,
    CharacterCardExportTarget,
)
from utils.paths import ensure_project_tree


def export_charapicker_json(
    card: CharacterCard,
    *,
    overwrite: bool = True,
    output_dir: Path | None = None,
) -> CharacterCardExportResult:
    path = _output_root(card.project_id, output_dir) / f"{card.card_id}.json"
    return _write_text_target(
        card,
        CharacterCardExportTarget.CHARAPICKER_JSON,
        path,
        json.dumps(card.model_dump(mode="json"), ensure_ascii=False, indent=2),
        overwrite=overwrite,
    )


def export_markdown(
    card: CharacterCard,
    *,
    overwrite: bool = True,
    output_dir: Path | None = None,
) -> CharacterCardExportResult:
    path = _output_root(card.project_id, output_dir) / f"{card.card_id}.md"
    return _write_text_target(
        card,
        CharacterCardExportTarget.CHARAPICKER_MARKDOWN,
        path,
        render_card_markdown(card),
        overwrite=overwrite,
    )


def export_html(
    card: CharacterCard,
    *,
    overwrite: bool = True,
    output_dir: Path | None = None,
) -> CharacterCardExportResult:
    path = _output_root(card.project_id, output_dir) / f"{card.card_id}.html"
    return _write_text_target(
        card,
        CharacterCardExportTarget.CHARAPICKER_HTML,
        path,
        render_card_html(card),
        overwrite=overwrite,
    )


def export_character_card_v2_json(
    card: CharacterCard,
    *,
    overwrite: bool = True,
    output_dir: Path | None = None,
) -> CharacterCardExportResult:
    formatted = to_character_card_v2_json(card)
    path = _output_root(card.project_id, output_dir) / f"{card.card_id}.character-card-v2.json"
    result = _write_text_target(
        card,
        CharacterCardExportTarget.CHARACTER_CARD_V2_JSON,
        path,
        json.dumps(formatted.payload, ensure_ascii=False, indent=2),
        overwrite=overwrite,
    )
    result.warnings.extend(formatted.warnings)
    return result


def export_astrbot_copy_markdown(
    card: CharacterCard,
    *,
    overwrite: bool = True,
    output_dir: Path | None = None,
) -> CharacterCardExportResult:
    formatted = to_astrbot_copy_markdown(card)
    path = _output_root(card.project_id, output_dir) / f"{card.card_id}.astrbot-copy.md"
    result = _write_text_target(
        card,
        CharacterCardExportTarget.ASTRBOT_COPY,
        path,
        str(formatted.payload),
        overwrite=overwrite,
    )
    result.warnings.extend(formatted.warnings)
    return result


def export_selected_targets(
    card: CharacterCard,
    targets: list[CharacterCardExportTarget],
    *,
    overwrite: bool = True,
    output_dir: Path | None = None,
) -> list[CharacterCardExportResult]:
    exporters = {
        CharacterCardExportTarget.CHARAPICKER_JSON: export_charapicker_json,
        CharacterCardExportTarget.CHARAPICKER_MARKDOWN: export_markdown,
        CharacterCardExportTarget.CHARAPICKER_HTML: export_html,
        CharacterCardExportTarget.CHARACTER_CARD_V2_JSON: export_character_card_v2_json,
        CharacterCardExportTarget.ASTRBOT_COPY: export_astrbot_copy_markdown,
    }
    results: list[CharacterCardExportResult] = []
    for target in targets:
        exporter = exporters.get(target)
        if exporter is None:
            results.append(
                CharacterCardExportResult(
                    target=target,
                    status=CharacterCardExportStatus.FAILED,
                    error="unsupported export target",
                )
            )
            continue
        results.append(exporter(card, overwrite=overwrite, output_dir=output_dir))
    return results


def _write_text_target(
    card: CharacterCard,
    target: CharacterCardExportTarget,
    path: Path,
    content: str,
    *,
    overwrite: bool,
) -> CharacterCardExportResult:
    if path.exists() and not overwrite:
        return CharacterCardExportResult(
            target=target,
            status=CharacterCardExportStatus.FAILED,
            output_path=str(path),
            error="output file already exists",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return CharacterCardExportResult(
        target=target,
        status=CharacterCardExportStatus.SUCCESS,
        output_path=str(path),
    )


def _output_root(project_id: str, output_dir: Path | None = None) -> Path:
    path = output_dir if output_dir is not None else ensure_project_tree(project_id).output / "character_cards"
    path.mkdir(parents=True, exist_ok=True)
    return path
