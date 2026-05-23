from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QElapsedTimer, QThread, QTimer, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SubtitleLabel,
    isDarkTheme,
)

from core import character_card_store as store
from core.character_card_exporter import export_astrbot_copy_markdown
from core.models import (
    CharacterCard,
    CharacterCardCrop,
    CharacterCardExportStatus,
    CharacterCardExportTarget,
    CharacterCardStatus,
    ProjectConfig,
)
from gui.widgets.character_card_detail_panel import CharacterCardDetailPanel
from gui.widgets.character_card_gallery import CharacterCardGallery
from gui.widgets.astrbot_copy_dialog import AstrBotCopyDialog
from gui.widgets.character_card_preview_dialog import CharacterCardPreviewDialog
from gui.widgets.cover_crop_dialog import CoverCropDialog
from gui.widgets.dialog_middleware import FluentDialog
from gui.widgets.streaming_text_session import StreamingTextSession
from gui.workers.character_card_workers import (
    CharacterCardCompileWorker,
    CharacterCardExportWorker,
    CharacterCardImportWorker,
    CharacterCardPreviewWorker,
)
from res.colors import (
    CHARACTER_CARD_DARK_BACKGROUND,
    CHARACTER_CARD_DARK_MUTED_TEXT,
    CHARACTER_CARD_LIGHT_BACKGROUND,
    CHARACTER_CARD_LIGHT_MUTED_TEXT,
)
from utils.i18n import t
from utils.cloud_model_presets import CloudModelPreset


class NewCharacterCardDialog(FluentDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(t("cards.new.dialog.title"), parent, width=460, height=238)

        description = BodyLabel(t("cards.new.dialog.description"), self.dialog_card)
        description.setWordWrap(True)
        self.content_layout.addWidget(description)

        self.name_edit = LineEdit(self.dialog_card)
        self.name_edit.setPlaceholderText(t("cards.new.dialog.label"))
        self.content_layout.addWidget(self.name_edit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = PushButton(t("cards.new.dialog.cancel"), self.dialog_card)
        self.create_button = PrimaryPushButton(t("cards.new.dialog.create"), self.dialog_card)
        actions.addWidget(cancel_button)
        actions.addWidget(self.create_button)
        self.content_layout.addLayout(actions)

        cancel_button.clicked.connect(self.reject)
        self.create_button.clicked.connect(self.accept)
        self.name_edit.textChanged.connect(self._sync_create_button)
        self.name_edit.returnPressed.connect(self._accept_if_ready)
        self._sync_create_button("")

    def character_name(self) -> str:
        return self.name_edit.text().strip()

    def _sync_create_button(self, text: str) -> None:
        self.create_button.setEnabled(bool(text.strip()))

    def _accept_if_ready(self) -> None:
        if self.create_button.isEnabled():
            self.accept()


class UnsavedCardSwitchDialog(FluentDialog):
    SAVE = "save"
    DISCARD = "discard"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(t("cards.switchUnsaved.dialog.title"), parent, width=520, height=236)
        self.choice = ""

        description = BodyLabel(t("cards.switchUnsaved.dialog.content"), self.dialog_card)
        description.setWordWrap(True)
        self.content_layout.addWidget(description)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = PushButton(t("cards.switchUnsaved.dialog.cancel"), self.dialog_card)
        discard_button = PushButton(t("cards.switchUnsaved.dialog.discard"), self.dialog_card)
        save_button = PrimaryPushButton(t("cards.switchUnsaved.dialog.save"), self.dialog_card)
        actions.addWidget(cancel_button)
        actions.addWidget(discard_button)
        actions.addWidget(save_button)
        self.content_layout.addLayout(actions)

        cancel_button.clicked.connect(self.reject)
        discard_button.clicked.connect(lambda: self._choose(self.DISCARD))
        save_button.clicked.connect(lambda: self._choose(self.SAVE))

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class CharacterCardLoadingDialog(FluentDialog):
    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent, width=660, height=420, close_rejects=False)
        self.close_button.hide()

        label = BodyLabel(message, self.dialog_card)
        label.setWordWrap(True)
        self.content_layout.addWidget(label)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(12)
        self.stage_label = CaptionLabel(t("cards.compile.stage.preparing"), self.dialog_card)
        self.stage_label.setWordWrap(True)
        self.elapsed_label = CaptionLabel("", self.dialog_card)
        self.elapsed_label.setMinimumWidth(120)
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.stage_label, 1)
        status_row.addWidget(self.elapsed_label, 0)
        self.content_layout.addLayout(status_row)

        progress = ProgressBar(self.dialog_card)
        progress.setRange(0, 0)
        self.content_layout.addWidget(progress)

        self.stream_output = PlainTextEdit(self.dialog_card)
        self.stream_output.setReadOnly(True)
        self.stream_output.setMinimumHeight(190)
        self.stream_output.setPlaceholderText(t("cards.compile.stream.placeholder"))
        self.content_layout.addWidget(self.stream_output)
        self._stream_session = StreamingTextSession(self.stream_output)
        self._elapsed_clock = QElapsedTimer()
        self._elapsed_clock.start()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_label)
        self._elapsed_timer.start()
        self._update_elapsed_label()

    def set_stage(self, text: str) -> None:
        self.stage_label.setText(text)

    def append_stream_delta(self, delta: str) -> None:
        if not delta:
            return
        if not self._stream_session.active:
            self._stream_session.start(t("cards.compile.stream.header"))
        self._stream_session.append_delta(delta)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._elapsed_timer.stop()
        super().closeEvent(event)

    def _update_elapsed_label(self) -> None:
        seconds = max(0, self._elapsed_clock.elapsed() // 1000)
        self.elapsed_label.setText(t("cards.compile.elapsed", elapsed=_format_elapsed(seconds)))


class CharacterCardPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("characterCardPage")
        self._project: ProjectConfig | None = None
        self._current_card: CharacterCard | None = None
        self._worker_thread: QThread | None = None
        self._worker: object | None = None
        self._model_preset_provider: Callable[[], CloudModelPreset | None] | None = None
        self._loading_dialog: CharacterCardLoadingDialog | None = None
        self._suppress_gallery_selection = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 10, 22, 16)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(1)
        header_text.addWidget(SubtitleLabel(t("cards.title"), self))
        self.project_label = CaptionLabel(t("cards.noProject"), self)
        self.project_label.setWordWrap(True)
        header_text.addWidget(self.project_label)
        header.addLayout(header_text, 1)
        header.addStretch(1)
        self.preview_draft_button = PushButton(t("cards.action.previewDraft"), self)
        self.import_button = PushButton(t("cards.action.import"), self)
        self.new_button = PrimaryPushButton(t("cards.action.new"), self)
        header.addWidget(self.preview_draft_button)
        header.addWidget(self.import_button)
        header.addWidget(self.new_button)
        root.addLayout(header)

        self.workbench_layout = QHBoxLayout()
        self.workbench_layout.setContentsMargins(0, 0, 0, 0)
        self.workbench_layout.setSpacing(8)
        self.gallery = CharacterCardGallery(self)
        self.detail = CharacterCardDetailPanel(self)
        self.gallery.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.workbench_layout.addWidget(self.gallery, 23)
        self.workbench_layout.addWidget(self.detail, 77)
        root.addLayout(self.workbench_layout, 1)

        self.gallery.cardSelected.connect(self._load_card)
        self.preview_draft_button.clicked.connect(self._preview_draft)
        self.new_button.clicked.connect(self._create_card)
        self.import_button.clicked.connect(self._import_card)
        self.detail.saveRequested.connect(self._save_metadata)
        self.detail.deleteRequested.connect(self._delete_card)
        self.detail.coverRequested.connect(self._choose_cover)
        self.detail.clearCoverRequested.connect(self._clear_cover)
        self.detail.previewRequested.connect(self._preview_current_card)
        self.detail.compileRequested.connect(self._compile_current_card)
        self.detail.exportRequested.connect(self._export_current_card)
        self.detail.astrbotRequested.connect(self._show_astrbot_current_card)
        self.set_project(None)
        self.apply_theme_colors()

    def set_model_preset_provider(self, provider: Callable[[], CloudModelPreset | None]) -> None:
        self._model_preset_provider = provider

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            background = CHARACTER_CARD_DARK_BACKGROUND
            muted = CHARACTER_CARD_DARK_MUTED_TEXT
        else:
            background = CHARACTER_CARD_LIGHT_BACKGROUND
            muted = CHARACTER_CARD_LIGHT_MUTED_TEXT
        self.setStyleSheet(
            f"""
            QWidget#characterCardPage {{
                background: {background};
            }}
            """
        )
        self.project_label.setStyleSheet(f"color: {muted};")
        self.gallery.apply_theme_colors()
        self.detail.apply_theme_colors()

    def set_project(self, project: ProjectConfig | None) -> None:
        self._project = project
        self._current_card = None
        has_project = project is not None
        for widget in (self.preview_draft_button, self.import_button, self.new_button, self.gallery):
            widget.setEnabled(has_project)
        if project is None:
            self.project_label.setText(t("cards.noProject"))
            self.gallery.set_cards([])
            self.detail.set_card(None)
            return
        self.project_label.setText(t("cards.project", name=project.name, project_id=project.project_id))
        self.refresh_gallery()

    def refresh_gallery(self, select_card_id: str = "") -> None:
        if self._project is None:
            return
        cards = store.list_card_summaries(self._project.project_id)
        self.gallery.set_cards(cards)
        if select_card_id:
            self.gallery.select_card(select_card_id)
        elif cards:
            self.gallery.select_card(cards[0].card_id)
        else:
            self.detail.set_card(None)

    def _create_card(self) -> None:
        if self._project is None:
            return
        dialog = NewCharacterCardDialog(self)
        if not dialog.exec():
            return
        name = dialog.character_name()
        card = store.create_empty_card(self._project.project_id, name)
        store.save_card(card)
        self.refresh_gallery(card.card_id)

    def _load_card(self, card_id: str) -> None:
        if self._project is None or not card_id:
            return
        if self._suppress_gallery_selection:
            return
        previous_card_id = self._current_card.card_id if self._current_card is not None else ""
        if previous_card_id == card_id:
            return
        if not self._confirm_unsaved_switch():
            self._select_gallery_silently(previous_card_id)
            return
        try:
            self._current_card = store.load_card(self._project.project_id, card_id)
        except Exception as exc:  # noqa: BLE001
            self._show_warning(t("cards.load.failed.title"), str(exc))
            self._current_card = None
        self.detail.set_card(self._current_card)

    def _save_metadata(self, *, silent: bool = False) -> bool:
        if self._current_card is None:
            return False
        original_name = self._current_card.identity.character_name
        original_editable_inputs = _editable_inputs_snapshot(self._current_card)
        original_compile_inputs = _compile_inputs_snapshot(self._current_card)
        updated = self.detail.apply_to_card(self._current_card)
        editable_inputs_changed = original_editable_inputs != _editable_inputs_snapshot(updated)
        compile_inputs_changed = original_compile_inputs != _compile_inputs_snapshot(updated)
        if not editable_inputs_changed:
            return True
        if updated.compile_status == CharacterCardStatus.COMPILED:
            if original_name != updated.identity.character_name:
                updated = store.mark_card_stale(updated, "character_name_changed")
            elif compile_inputs_changed:
                updated = store.mark_card_stale(updated, "compile_inputs_changed")
        store.save_card(updated)
        self._current_card = updated
        self.detail.set_card(updated)
        self.refresh_gallery(updated.card_id)
        if not silent:
            self._show_success(t("cards.save.success.title"), t("cards.save.success.content"))
        return True

    def _delete_card(self) -> None:
        if self._project is None or self._current_card is None:
            return
        dialog = MessageBox(
            t("cards.delete.dialog.title"),
            t("cards.delete.dialog.content", name=self._current_card.identity.display_name or self._current_card.card_id),
            self.window(),
        )
        dialog.yesButton.setText(t("cards.delete.dialog.confirm"))
        dialog.cancelButton.setText(t("cards.delete.dialog.cancel"))
        if not dialog.exec():
            return
        store.delete_card(self._project.project_id, self._current_card.card_id)
        self._current_card = None
        self.refresh_gallery()

    def _choose_cover(self) -> None:
        if self._project is None or self._current_card is None:
            return
        file_name, _ = QFileDialog.getOpenFileName(self, t("cards.cover.fileDialog"), "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not file_name:
            return
        image_path = Path(file_name)
        dialog = CoverCropDialog(image_path, self)
        if not dialog.exec():
            return
        cover_path, original_path = store.resolve_cover_paths(
            self._project.project_id,
            self._current_card.card_id,
            image_path.suffix or ".png",
        )
        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, original_path)
        image = QImage(str(image_path))
        cropped = image.copy(dialog.crop_rect)
        if cropped.isNull() or not cropped.save(str(cover_path), "PNG"):
            self._show_warning(t("cards.cover.failed.title"), t("cards.cover.failed.content"))
            return
        card = self._current_card.model_copy(deep=True)
        card.assets.cover_path = "cover.png"
        card.assets.original_cover_path = original_path.name
        card.assets.cover_aspect_ratio = "9:16"
        card.assets.crop = CharacterCardCrop(
            source_width=image.width(),
            source_height=image.height(),
            x=dialog.crop_rect.x(),
            y=dialog.crop_rect.y(),
            width=dialog.crop_rect.width(),
            height=dialog.crop_rect.height(),
            scale=dialog.crop_scale,
        )
        store.save_card(card)
        self._current_card = card
        self.detail.set_card(card)
        self.refresh_gallery(card.card_id)

    def _clear_cover(self) -> None:
        if self._current_card is None:
            return
        card = self._current_card.model_copy(deep=True)
        card.assets.cover_path = ""
        card.assets.crop = None
        store.save_card(card)
        self._current_card = card
        self.detail.set_card(card)
        self.refresh_gallery(card.card_id)

    def _preview_current_card(self) -> None:
        if self._current_card is not None:
            CharacterCardPreviewDialog(
                self._current_card,
                self,
                stale=self.detail.is_result_stale(),
            ).exec()

    def _show_astrbot_current_card(self) -> None:
        if self._current_card is not None:
            AstrBotCopyDialog(self._current_card, self).exec()

    def _compile_current_card(self) -> None:
        if self._current_card is None:
            return
        if not self._save_metadata(silent=True):
            return
        if self._current_card is None:
            return
        cloud_preset = self._model_preset_provider() if self._model_preset_provider is not None else None
        worker = CharacterCardCompileWorker(self._current_card, cloud_preset)
        worker.succeeded.connect(self._on_compile_succeeded)
        worker.failed.connect(self._on_compile_failed)
        worker.stageChanged.connect(self._on_compile_stage_changed)
        worker.streamDelta.connect(self._on_compile_stream_delta)
        self._show_loading(t("cards.compile.loading.title"), t("cards.compile.loading.content"))
        if not self._start_worker(worker):
            self._hide_loading()

    def _preview_draft(self) -> None:
        if self._project is None:
            return
        character_name = self._current_card.identity.character_name if self._current_card else ""
        worker = CharacterCardPreviewWorker(self._project.project_id, character_name)
        worker.succeeded.connect(lambda card: CharacterCardPreviewDialog(card, self, preview_only=True).exec())
        worker.failed.connect(lambda error: self._show_warning(t("cards.preview.failed.title"), error))
        self._start_worker(worker)

    def _import_card(self) -> None:
        if self._project is None:
            return
        file_name, _ = QFileDialog.getOpenFileName(self, t("cards.import.fileDialog"), "", "JSON (*.json)")
        if not file_name:
            return
        worker = CharacterCardImportWorker(self._project.project_id, Path(file_name))
        worker.succeeded.connect(lambda card: self.refresh_gallery(card.card_id))
        worker.failed.connect(lambda error: self._show_warning(t("cards.import.failed.title"), error))
        self._start_worker(worker)

    def _export_current_card(self) -> None:
        if self._current_card is None:
            return
        directory = QFileDialog.getExistingDirectory(self, t("cards.export.directoryDialog"), "")
        if not directory:
            return
        targets = [
            CharacterCardExportTarget.CHARAPICKER_JSON,
            CharacterCardExportTarget.CHARAPICKER_MARKDOWN,
            CharacterCardExportTarget.CHARAPICKER_HTML,
            CharacterCardExportTarget.CHARACTER_CARD_V2_JSON,
            CharacterCardExportTarget.ASTRBOT_COPY,
        ]
        worker = CharacterCardExportWorker(self._current_card, targets, Path(directory))
        worker.succeeded.connect(self._on_export_succeeded)
        worker.failed.connect(lambda error: self._show_warning(t("cards.export.failed.title"), error))
        self._start_worker(worker)

    def _on_compile_succeeded(self, card: CharacterCard) -> None:
        self._current_card = card
        self.detail.set_card(card)
        self.refresh_gallery(card.card_id)
        if self.detail.export_astrbot_after_compile.isChecked():
            result = export_astrbot_copy_markdown(card)
            if result.status != CharacterCardExportStatus.SUCCESS:
                self._show_warning(t("cards.astrbot.partial.title"), result.error or "; ".join(result.warnings))
        self._show_success(t("cards.compile.success.title"), t("cards.compile.success.content"))

    def _on_compile_failed(self, error: str) -> None:
        card = getattr(self._worker, "card", None)
        if not isinstance(card, CharacterCard):
            card = self._current_card
        if card is not None:
            failed = card.model_copy(deep=True)
            failed.compile_status = CharacterCardStatus.FAILED
            failed.quality.needs_review = True
            failed.quality.last_error = error
            if error and error not in failed.quality.warnings:
                failed.quality.warnings = [*failed.quality.warnings, error]
            store.save_card(failed)
            self._current_card = failed
            self.detail.set_card(failed)
            self.refresh_gallery(failed.card_id)
        self._show_warning(t("cards.compile.failed.title"), error)

    def _on_compile_stage_changed(self, stage: str) -> None:
        if self._loading_dialog is None:
            return
        self._loading_dialog.set_stage(t(f"cards.compile.stage.{stage}"))

    def _on_compile_stream_delta(self, delta: str) -> None:
        if self._loading_dialog is None:
            return
        self._loading_dialog.append_stream_delta(delta)

    def _on_export_succeeded(self, results: list) -> None:
        ok_paths = [
            result.output_path
            for result in results
            if getattr(result, "status", None) == CharacterCardExportStatus.SUCCESS and result.output_path
        ]
        output_dir = str(Path(ok_paths[0]).parent) if ok_paths else ""
        issues = _export_issue_summary(results)
        if issues:
            self._show_warning(
                t("cards.export.partial.title"),
                t(
                    "cards.export.partial.content",
                    count=len(ok_paths),
                    path=output_dir or "-",
                    issue_count=len(issues),
                    summary="; ".join(issues[:3]),
                ),
            )
            return
        self._show_success(
            t("cards.export.success.title"),
            t("cards.export.success.content", count=len(ok_paths), path=output_dir),
        )

    def _start_worker(self, worker: object) -> bool:
        if self._worker_thread is not None:
            self._show_warning(t("cards.busy.title"), t("cards.busy.content"))
            return False
        thread = QThread(self)
        self._worker_thread = thread
        self._worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._hide_loading)
        worker.finished.connect(self._clear_worker)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return True

    def _clear_worker(self) -> None:
        self._worker_thread = None
        self._worker = None

    def _confirm_unsaved_switch(self) -> bool:
        if not self.detail.is_dirty():
            return True
        dialog = UnsavedCardSwitchDialog(self)
        if not dialog.exec():
            return False
        if dialog.choice == UnsavedCardSwitchDialog.SAVE:
            return self._save_metadata(silent=True)
        return dialog.choice == UnsavedCardSwitchDialog.DISCARD

    def _select_gallery_silently(self, card_id: str) -> None:
        if not card_id:
            return
        self._suppress_gallery_selection = True
        try:
            self.gallery.select_card(card_id)
        finally:
            self._suppress_gallery_selection = False

    def _show_loading(self, title: str, content: str) -> None:
        self._hide_loading()
        self._loading_dialog = CharacterCardLoadingDialog(title, content, self)
        self._loading_dialog.show()

    def _hide_loading(self) -> None:
        if self._loading_dialog is None:
            return
        self._loading_dialog.close()
        self._loading_dialog.deleteLater()
        self._loading_dialog = None

    def _show_success(self, title: str, content: str) -> None:
        InfoBar.success(title=title, content=content, parent=self.window(), position=InfoBarPosition.TOP_RIGHT, duration=3500)

    def _show_warning(self, title: str, content: str) -> None:
        InfoBar.warning(title=title, content=content, parent=self.window(), position=InfoBarPosition.TOP_RIGHT, duration=5500)


def _compile_inputs_snapshot(card: CharacterCard) -> tuple[object, ...]:
    return (
        card.identity.character_name,
        card.user_metadata.notes,
        card.user_metadata.compile_variant,
        card.user_metadata.compile_requirements,
        card.user_metadata.extra_dialogue_count,
    )


def _editable_inputs_snapshot(card: CharacterCard) -> tuple[object, ...]:
    return (
        card.identity.character_name,
        card.identity.display_name,
        tuple(card.identity.aliases),
        tuple(card.user_metadata.tags),
        card.user_metadata.notes,
        card.user_metadata.compile_variant,
        card.user_metadata.compile_requirements,
        card.user_metadata.extra_dialogue_count,
    )


def _export_issue_summary(results: list) -> list[str]:
    issues: list[str] = []
    for result in results:
        target = getattr(getattr(result, "target", None), "value", str(getattr(result, "target", "")))
        status = getattr(result, "status", None)
        error = str(getattr(result, "error", "") or "").strip()
        warnings = [str(item).strip() for item in getattr(result, "warnings", []) if str(item).strip()]
        if status == CharacterCardExportStatus.FAILED:
            issues.append(f"{target}: {error or 'failed'}")
        for warning in warnings:
            issues.append(f"{target}: {warning}")
    return list(dict.fromkeys(issues))


def _format_elapsed(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
