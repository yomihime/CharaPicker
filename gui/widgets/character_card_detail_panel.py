from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    CheckBox,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
)

from core.models import CharacterCard
from utils.i18n import t


class CharacterCardDetailPanel(QWidget):
    saveRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    coverRequested = pyqtSignal()
    clearCoverRequested = pyqtSignal()
    previewRequested = pyqtSignal()
    compileRequested = pyqtSignal()
    exportRequested = pyqtSignal()
    astrbotRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card: CharacterCard | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.status_label = CaptionLabel(t("cards.status.noSelection"), self)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        form_card = CardWidget(self)
        form_card.setBorderRadius(8)
        form_layout = QFormLayout(form_card)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(10)

        self.character_name = LineEdit(form_card)
        self.display_name = LineEdit(form_card)
        self.aliases = LineEdit(form_card)
        self.tags = LineEdit(form_card)
        self.notes = PlainTextEdit(form_card)
        self.notes.setFixedHeight(88)
        self.extra_dialogue_count = LineEdit(form_card)
        self.extra_dialogue_count.setValidator(QIntValidator(0, 100, self.extra_dialogue_count))
        self.extra_dialogue_count.setPlaceholderText(t("cards.field.extraDialogueCount.placeholder"))
        self.compile_requirements = PlainTextEdit(form_card)
        self.compile_requirements.setFixedHeight(88)
        self.compile_requirements.setPlaceholderText(t("cards.field.compileRequirements.placeholder"))
        form_layout.addRow(BodyLabel(t("cards.field.characterName"), form_card), self.character_name)
        form_layout.addRow(BodyLabel(t("cards.field.displayName"), form_card), self.display_name)
        form_layout.addRow(BodyLabel(t("cards.field.aliases"), form_card), self.aliases)
        form_layout.addRow(BodyLabel(t("cards.field.tags"), form_card), self.tags)
        form_layout.addRow(BodyLabel(t("cards.field.notes"), form_card), self.notes)
        form_layout.addRow(
            BodyLabel(t("cards.field.extraDialogueCount"), form_card),
            self.extra_dialogue_count,
        )
        form_layout.addRow(
            BodyLabel(t("cards.field.compileRequirements"), form_card),
            self.compile_requirements,
        )
        root.addWidget(form_card)

        self.export_astrbot_after_compile = CheckBox(t("cards.option.exportAstrbotAfterCompile"), self)
        root.addWidget(self.export_astrbot_after_compile)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.save_button = PrimaryPushButton(t("cards.action.save"), self)
        self.cover_button = PushButton(t("cards.action.cover"), self)
        self.clear_cover_button = PushButton(t("cards.action.clearCover"), self)
        self.preview_button = PushButton(t("cards.action.preview"), self)
        self.compile_button = PushButton(t("cards.action.compile"), self)
        self.export_button = PushButton(t("cards.action.export"), self)
        self.astrbot_button = PushButton(t("cards.action.astrbot"), self)
        self.delete_button = PushButton(t("cards.action.delete"), self)
        for button in (
            self.save_button,
            self.cover_button,
            self.clear_cover_button,
            self.preview_button,
            self.compile_button,
            self.export_button,
            self.astrbot_button,
            self.delete_button,
        ):
            actions.addWidget(button)
        root.addLayout(actions)
        root.addStretch(1)

        self.save_button.clicked.connect(self.saveRequested)
        self.cover_button.clicked.connect(self.coverRequested)
        self.clear_cover_button.clicked.connect(self.clearCoverRequested)
        self.preview_button.clicked.connect(self.previewRequested)
        self.compile_button.clicked.connect(self.compileRequested)
        self.export_button.clicked.connect(self.exportRequested)
        self.astrbot_button.clicked.connect(self.astrbotRequested)
        self.delete_button.clicked.connect(self.deleteRequested)
        self.set_card(None)

    def set_card(self, card: CharacterCard | None) -> None:
        self._card = card
        enabled = card is not None
        for widget in (
            self.character_name,
            self.display_name,
            self.aliases,
            self.tags,
            self.notes,
            self.extra_dialogue_count,
            self.compile_requirements,
            self.save_button,
            self.cover_button,
            self.clear_cover_button,
            self.preview_button,
            self.compile_button,
            self.export_button,
            self.astrbot_button,
            self.delete_button,
            self.export_astrbot_after_compile,
        ):
            widget.setEnabled(enabled)
        if card is None:
            self.status_label.setText(t("cards.status.noSelection"))
            self.character_name.clear()
            self.display_name.clear()
            self.aliases.clear()
            self.tags.clear()
            self.notes.clear()
            self.extra_dialogue_count.clear()
            self.compile_requirements.clear()
            return
        self.status_label.setText(
            t(
                "cards.status.summary",
                status=card.compile_status.value,
                source=card.compile_source.value,
                revision=card.revision,
            )
        )
        self.character_name.setText(card.identity.character_name)
        self.display_name.setText(card.identity.display_name)
        self.aliases.setText(", ".join(card.identity.aliases))
        self.tags.setText(", ".join(card.user_metadata.tags))
        self.notes.setPlainText(card.user_metadata.notes)
        dialogue_count = card.user_metadata.extra_dialogue_count
        self.extra_dialogue_count.setText("" if dialogue_count is None else str(dialogue_count))
        self.compile_requirements.setPlainText(card.user_metadata.compile_requirements)

    def apply_to_card(self, card: CharacterCard) -> CharacterCard:
        output = card.model_copy(deep=True)
        original = _editable_snapshot(output)
        output.identity.character_name = self.character_name.text().strip()
        output.identity.display_name = self.display_name.text().strip()
        output.identity.aliases = _split_csv(self.aliases.text())
        output.user_metadata.tags = _split_csv(self.tags.text())
        output.user_metadata.notes = self.notes.toPlainText().strip()
        output.user_metadata.extra_dialogue_count = _optional_dialogue_count(
            self.extra_dialogue_count.text()
        )
        output.user_metadata.compile_requirements = self.compile_requirements.toPlainText().strip()
        if not output.identity.display_name:
            output.identity.display_name = output.identity.character_name
        if _editable_snapshot(output) != original:
            output.revision += 1
        return output


def _editable_snapshot(card: CharacterCard) -> tuple[object, ...]:
    return (
        card.identity.character_name,
        card.identity.display_name,
        tuple(card.identity.aliases),
        tuple(card.user_metadata.tags),
        card.user_metadata.notes,
        card.user_metadata.extra_dialogue_count,
        card.user_metadata.compile_requirements,
    )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\uff0c", ",").split(",") if item.strip()]


def _optional_dialogue_count(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return max(0, min(100, int(text)))
    except ValueError:
        return None
