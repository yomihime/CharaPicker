from __future__ import annotations

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
            self.stageChanged.emit("done")
            self.succeeded.emit(compiled)
        except Exception as exc:  # noqa: BLE001
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
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
