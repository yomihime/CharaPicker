from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PlainTextEdit,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui.widgets.dialog_middleware import FluentDialog
from utils.ai_model_middleware import load_default_prompts
from utils.i18n import t
from utils.prompt_preferences import PromptOverride, clear_prompt_override, prompt_override, set_prompt_override


LOGGER = logging.getLogger(__name__)
PROMPT_VARIABLES = {
    "targeted_insight": ("target_characters", "chunk_text"),
    "character_compile": ("character", "current_state", "evidence_chunk"),
    "final_polish": ("character", "character_state"),
}


class PromptHelpDialog(FluentDialog):
    def __init__(self, purpose: str, parent: QWidget | None = None) -> None:
        super().__init__(
            t("prompts.help.title"),
            parent,
            width=560,
            height=330,
            margins=(24, 20, 24, 18),
            spacing=12,
        )
        self.close_button.hide()

        intro_label = CaptionLabel(t("prompts.help.intro"), self.dialog_card)
        intro_label.setWordWrap(True)
        self.content_layout.addWidget(intro_label)

        variable_panel = QWidget(self.dialog_card)
        variable_layout = QGridLayout(variable_panel)
        variable_layout.setContentsMargins(0, 4, 0, 4)
        variable_layout.setHorizontalSpacing(18)
        variable_layout.setVerticalSpacing(8)
        variable_layout.addWidget(StrongBodyLabel(t("prompts.help.variables.title"), variable_panel), 0, 0, 1, 2)
        for row, variable in enumerate(PROMPT_VARIABLES.get(purpose, ()), start=1):
            name_label = CaptionLabel(f"{{{variable}}}", variable_panel)
            name_label.setMinimumWidth(148)
            description_label = CaptionLabel(t(f"prompts.help.variable.{variable}"), variable_panel)
            description_label.setWordWrap(True)
            variable_layout.addWidget(name_label, row, 0)
            variable_layout.addWidget(description_label, row, 1)
        variable_layout.setColumnStretch(0, 0)
        variable_layout.setColumnStretch(1, 1)
        self.content_layout.addWidget(variable_panel)

        self.content_layout.addSpacing(2)
        self.content_layout.addWidget(StrongBodyLabel(t("prompts.help.note.title"), self.dialog_card))
        for key in ("prompts.help.note.braces", "prompts.help.note.blank"):
            note_label = CaptionLabel(t(key), self.dialog_card)
            note_label.setWordWrap(True)
            self.content_layout.addWidget(note_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        confirm_button = PushButton(t("prompts.help.confirm"), self.dialog_card)
        actions.addWidget(confirm_button)
        self.content_layout.addLayout(actions)
        confirm_button.clicked.connect(self.accept)


class PromptPage(QWidget):
    promptChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("promptPage")
        self._default_prompts = load_default_prompts()
        self._purpose_values = list(self._default_prompts.keys())
        self._loading_prompt = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(SubtitleLabel(t("prompts.title"), self))

        card = CardWidget(self)
        card.setBorderRadius(8)
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setSpacing(12)

        self.purpose_combo = ComboBox(card)
        for purpose in self._purpose_values:
            self.purpose_combo.addItem(t(f"prompts.purpose.{purpose}"))

        self.system_prompt_edit = PlainTextEdit(card)
        self.system_prompt_edit.setMinimumHeight(140)
        self.user_template_edit = PlainTextEdit(card)
        self.user_template_edit.setMinimumHeight(220)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.help_button = PushButton(t("prompts.help.button"), card)
        self.restore_button = PushButton(t("prompts.restoreDefault"), card)
        self.save_button = PushButton(t("prompts.save"), card)
        action_row.addWidget(self.help_button)
        action_row.addWidget(self.restore_button)
        action_row.addWidget(self.save_button)

        form.addRow(t("prompts.field.purpose"), self.purpose_combo)
        form.addRow(t("prompts.field.system"), self.system_prompt_edit)
        form.addRow(t("prompts.field.userTemplate"), self.user_template_edit)
        form.addRow(BodyLabel("", card), action_row)
        root.addWidget(card)
        root.addStretch(1)

        self.purpose_combo.currentIndexChanged.connect(self._load_selected_prompt)
        self.help_button.clicked.connect(self._show_prompt_help)
        self.save_button.clicked.connect(self._save_selected_prompt)
        self.restore_button.clicked.connect(self._restore_selected_default)
        self._load_selected_prompt()

    def _current_purpose(self) -> str | None:
        index = self.purpose_combo.currentIndex()
        if not 0 <= index < len(self._purpose_values):
            return None
        return self._purpose_values[index]

    def _show_prompt_help(self) -> None:
        purpose = self._current_purpose()
        if purpose is None:
            return
        dialog = PromptHelpDialog(purpose, self)
        dialog.exec()

    def _load_selected_prompt(self) -> None:
        purpose = self._current_purpose()
        if purpose is None:
            return

        default_prompt = self._default_prompts[purpose]
        override = prompt_override(purpose)
        self._loading_prompt = True
        self.system_prompt_edit.setPlainText(override.system.strip() or default_prompt.system)
        self.user_template_edit.setPlainText(override.user_template.strip() or default_prompt.user_template)
        self._loading_prompt = False

    def _save_selected_prompt(self) -> None:
        if self._loading_prompt:
            return
        purpose = self._current_purpose()
        if purpose is None:
            return

        default_prompt = self._default_prompts[purpose]
        system_prompt = self.system_prompt_edit.toPlainText().strip()
        user_template = self.user_template_edit.toPlainText().strip()
        override = PromptOverride(
            system="" if system_prompt == default_prompt.system.strip() else system_prompt,
            user_template="" if user_template == default_prompt.user_template.strip() else user_template,
        )
        set_prompt_override(purpose, override)
        self._load_selected_prompt()
        self.promptChanged.emit()
        InfoBar.success(
            title=t("prompts.save.success.title"),
            content=t("prompts.save.success.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )

    def _restore_selected_default(self) -> None:
        purpose = self._current_purpose()
        if purpose is None:
            return

        clear_prompt_override(purpose)
        self._load_selected_prompt()
        self.promptChanged.emit()
        InfoBar.info(
            title=t("prompts.restore.success.title"),
            content=t("prompts.restore.success.content"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )
