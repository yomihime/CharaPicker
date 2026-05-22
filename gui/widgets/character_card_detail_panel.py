from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget,
    CaptionLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from core.models import CharacterCard, CharacterCardCompileVariant
from utils.i18n import t


COMPILE_VARIANTS = (
    CharacterCardCompileVariant.GENERAL,
    CharacterCardCompileVariant.ASTRBOT,
    CharacterCardCompileVariant.CHARACTER_CARD_V2,
)


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

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header.addWidget(StrongBodyLabel(t("cards.detail.title"), self))
        header.addStretch(1)
        self.status_label = CaptionLabel(t("cards.status.noSelection"), self)
        self.status_label.setWordWrap(True)
        header.addWidget(self.status_label)
        root.addLayout(header)

        form_card = CardWidget(self)
        form_card.setBorderRadius(8)
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(18, 16, 18, 16)
        form_layout.setSpacing(14)

        self.character_name = LineEdit(form_card)
        self.display_name = LineEdit(form_card)
        self.aliases = LineEdit(form_card)
        self.tags = LineEdit(form_card)
        self.notes = PlainTextEdit(form_card)
        self.notes.setMinimumHeight(128)
        self.compile_variant = ComboBox(form_card)
        for variant in COMPILE_VARIANTS:
            self.compile_variant.addItem(t(f"cards.compileVariant.{variant.value}"))
        self.extra_dialogue_count = LineEdit(form_card)
        self.extra_dialogue_count.setValidator(QIntValidator(0, 100, self.extra_dialogue_count))
        self.extra_dialogue_count.setPlaceholderText(t("cards.field.extraDialogueCount.placeholder"))
        self.compile_requirements = PlainTextEdit(form_card)
        self.compile_requirements.setMinimumHeight(128)
        self.compile_requirements.setPlaceholderText(t("cards.field.compileRequirements.placeholder"))

        form_layout.addWidget(StrongBodyLabel(t("cards.detail.identity"), form_card))
        identity_grid = QGridLayout()
        identity_grid.setContentsMargins(0, 0, 0, 0)
        identity_grid.setHorizontalSpacing(14)
        identity_grid.setVerticalSpacing(10)
        _add_labeled_field(
            identity_grid,
            0,
            0,
            t("cards.field.characterName"),
            self.character_name,
            form_card,
        )
        _add_labeled_field(
            identity_grid,
            0,
            2,
            t("cards.field.displayName"),
            self.display_name,
            form_card,
        )
        _add_labeled_field(identity_grid, 1, 0, t("cards.field.aliases"), self.aliases, form_card)
        _add_labeled_field(identity_grid, 1, 2, t("cards.field.tags"), self.tags, form_card)
        identity_grid.setColumnStretch(1, 1)
        identity_grid.setColumnStretch(3, 1)
        form_layout.addLayout(identity_grid)

        text_grid = QGridLayout()
        text_grid.setContentsMargins(0, 0, 0, 0)
        text_grid.setHorizontalSpacing(14)
        text_grid.setVerticalSpacing(8)
        text_grid.addWidget(CaptionLabel(t("cards.field.notes"), form_card), 0, 0)
        text_grid.addWidget(CaptionLabel(t("cards.field.compileRequirements"), form_card), 0, 1)
        text_grid.addWidget(self.notes, 1, 0)
        text_grid.addWidget(self.compile_requirements, 1, 1)
        text_grid.setColumnStretch(0, 1)
        text_grid.setColumnStretch(1, 1)
        form_layout.addLayout(text_grid, 1)

        form_layout.addWidget(StrongBodyLabel(t("cards.detail.compile"), form_card))
        compile_grid = QGridLayout()
        compile_grid.setContentsMargins(0, 0, 0, 0)
        compile_grid.setHorizontalSpacing(14)
        compile_grid.setVerticalSpacing(10)
        _add_labeled_field(
            compile_grid,
            0,
            0,
            t("cards.field.compileVariant"),
            self.compile_variant,
            form_card,
        )
        _add_labeled_field(
            compile_grid,
            0,
            2,
            t("cards.field.extraDialogueCount"),
            self.extra_dialogue_count,
            form_card,
        )
        compile_grid.setColumnStretch(1, 1)
        compile_grid.setColumnStretch(3, 1)
        form_layout.addLayout(compile_grid)

        self.export_astrbot_after_compile = CheckBox(
            t("cards.option.exportAstrbotAfterCompile"),
            form_card,
        )
        form_layout.addWidget(self.export_astrbot_after_compile)
        root.addWidget(form_card, 1)

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
        for button in (self.save_button, self.cover_button, self.clear_cover_button):
            button.setMinimumWidth(104)
            actions.addWidget(button)
        actions.addStretch(1)
        for button in (self.preview_button, self.compile_button, self.export_button, self.astrbot_button):
            button.setMinimumWidth(112)
            actions.addWidget(button)
        self.delete_button.setMinimumWidth(96)
        actions.addWidget(self.delete_button)
        root.addLayout(actions)

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
            self.compile_variant,
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
            self._set_compile_variant(CharacterCardCompileVariant.GENERAL)
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
        self._set_compile_variant(card.user_metadata.compile_variant)
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
        output.user_metadata.compile_variant = self._current_compile_variant()
        output.user_metadata.extra_dialogue_count = _optional_dialogue_count(
            self.extra_dialogue_count.text()
        )
        output.user_metadata.compile_requirements = self.compile_requirements.toPlainText().strip()
        if not output.identity.display_name:
            output.identity.display_name = output.identity.character_name
        if _editable_snapshot(output) != original:
            output.revision += 1
        return output

    def _set_compile_variant(self, variant: CharacterCardCompileVariant) -> None:
        try:
            index = COMPILE_VARIANTS.index(variant)
        except ValueError:
            index = 0
        self.compile_variant.setCurrentIndex(index)

    def _current_compile_variant(self) -> CharacterCardCompileVariant:
        index = self.compile_variant.currentIndex()
        if 0 <= index < len(COMPILE_VARIANTS):
            return COMPILE_VARIANTS[index]
        return CharacterCardCompileVariant.GENERAL


def _editable_snapshot(card: CharacterCard) -> tuple[object, ...]:
    return (
        card.identity.character_name,
        card.identity.display_name,
        tuple(card.identity.aliases),
        tuple(card.user_metadata.tags),
        card.user_metadata.notes,
        card.user_metadata.compile_variant,
        card.user_metadata.extra_dialogue_count,
        card.user_metadata.compile_requirements,
    )


def _add_labeled_field(
    layout: QGridLayout,
    row: int,
    column: int,
    label_text: str,
    widget: QWidget,
    parent: QWidget,
) -> None:
    layout.addWidget(_field_label(label_text, parent), row, column)
    layout.addWidget(widget, row, column + 1)


def _field_label(text: str, parent: QWidget) -> CaptionLabel:
    label = CaptionLabel(text, parent)
    label.setMinimumWidth(112)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label


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
