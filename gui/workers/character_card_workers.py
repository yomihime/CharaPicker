from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core import character_card_store as store
from core.character_card_compiler import (
    compile_card_from_knowledge_base,
    compile_preview_card_from_preview_knowledge_base,
)
from core.character_card_exporter import export_selected_targets
from core.character_card_importer import import_charapicker_card
from core.models import CharacterCard, CharacterCardExportTarget
from utils.cloud_model_presets import CloudModelPreset


LOGGER = logging.getLogger(__name__)


class CharacterCardCompileWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    stageChanged = pyqtSignal(str)
    streamDelta = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, card: CharacterCard, cloud_preset: CloudModelPreset | None = None) -> None:
        super().__init__()
        self.card = card
        self.cloud_preset = cloud_preset

    def run(self) -> None:
        try:
            compiled = compile_card_from_knowledge_base(
                self.card,
                cloud_preset=self.cloud_preset,
                on_stage=self.stageChanged.emit,
                on_stream_delta=self.streamDelta.emit,
            )
            self.stageChanged.emit("saving")
            store.save_card(compiled)
            LOGGER.info(
                "Character card compile worker succeeded; project_id=%s card_id=%s status=%s evidence_count=%s",
                compiled.project_id,
                compiled.card_id,
                compiled.compile_status.value,
                compiled.evidence.evidence_count,
            )
            self.stageChanged.emit("done")
            self.succeeded.emit(compiled)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Character card compile worker failed; project_id=%s card_id=%s",
                self.card.project_id,
                self.card.card_id,
                exc_info=True,
            )
            self.stageChanged.emit("failed")
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class CharacterCardPreviewWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, project_id: str, character_name: str = "") -> None:
        super().__init__()
        self.project_id = project_id
        self.character_name = character_name

    def run(self) -> None:
        try:
            card = compile_preview_card_from_preview_knowledge_base(self.project_id, self.character_name)
            store.save_preview_card(card)
            self.succeeded.emit(card)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Character card preview worker failed; project_id=%s character=%s",
                self.project_id,
                self.character_name,
                exc_info=True,
            )
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class CharacterCardImportWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, project_id: str, path: Path) -> None:
        super().__init__()
        self.project_id = project_id
        self.path = path

    def run(self) -> None:
        try:
            self.succeeded.emit(import_charapicker_card(self.project_id, self.path))
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Character card import worker failed; project_id=%s file_name=%s",
                self.project_id,
                self.path.name,
                exc_info=True,
            )
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class CharacterCardExportWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        card: CharacterCard,
        targets: list[CharacterCardExportTarget],
        output_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.card = card
        self.targets = list(targets)
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            self.succeeded.emit(export_selected_targets(self.card, self.targets, output_dir=self.output_dir))
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Character card export worker failed; project_id=%s card_id=%s",
                self.card.project_id,
                self.card.card_id,
                exc_info=True,
            )
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
