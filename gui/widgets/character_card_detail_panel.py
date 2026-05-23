from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    isDarkTheme,
)

from core import character_card_store as store
from core.models import CharacterCard, CharacterCardCompileVariant, CharacterCardStatus
from gui.widgets.chip_tag_editor import ChipTagEditor, FlowLayout
from res.colors import (
    CHARACTER_CARD_DANGER,
    CHARACTER_CARD_DARK_BORDER,
    CHARACTER_CARD_DARK_MUTED_TEXT,
    CHARACTER_CARD_DARK_PANEL,
    CHARACTER_CARD_DARK_PANEL_ALT,
    CHARACTER_CARD_DARK_TEXT,
    CHARACTER_CARD_LIGHT_BORDER,
    CHARACTER_CARD_LIGHT_MUTED_TEXT,
    CHARACTER_CARD_LIGHT_PANEL,
    CHARACTER_CARD_LIGHT_PANEL_ALT,
    CHARACTER_CARD_LIGHT_TEXT,
)
from utils.i18n import t


COMPILE_VARIANTS = (
    CharacterCardCompileVariant.GENERAL,
    CharacterCardCompileVariant.ASTRBOT,
    CharacterCardCompileVariant.CHARACTER_CARD_V2,
)
TEXT_LIMIT = 3000


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
        self._baseline: tuple[object, ...] | None = None
        self._setting_card = False
        self._dirty = False
        self.setMinimumWidth(0)

        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(16)

        self.editor_scroll = _make_scroll_area(self)
        self.editor_scroll.setMinimumWidth(0)
        self.editor_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.editor_content = QWidget(self.editor_scroll)
        self.editor_content.setMinimumWidth(0)
        self.editor_layout = QVBoxLayout(self.editor_content)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_layout.setSpacing(12)
        self.editor_scroll.setWidget(self.editor_content)
        self.root_layout.addWidget(self.editor_scroll, 52)

        self.inspector_scroll = _make_scroll_area(self)
        self.inspector_scroll.setMinimumWidth(0)
        self.inspector_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.inspector_content = QWidget(self.inspector_scroll)
        self.inspector_content.setMinimumWidth(0)
        self.inspector_layout = QVBoxLayout(self.inspector_content)
        self.inspector_layout.setContentsMargins(0, 0, 0, 0)
        self.inspector_layout.setSpacing(12)
        self.inspector_scroll.setWidget(self.inspector_content)
        self.root_layout.addWidget(self.inspector_scroll, 24)

        self._build_editor()
        self._build_inspector()
        self._connect_dirty_signals()
        self.apply_theme_colors()
        self.set_card(None)

    def set_card(self, card: CharacterCard | None) -> None:
        self._setting_card = True
        self._card = card
        enabled = card is not None
        for widget in self._editable_widgets():
            widget.setEnabled(enabled)
        for button in self._action_widgets():
            button.setEnabled(enabled)

        if card is None:
            self._clear_fields()
            self.status_label.setText(t("cards.status.noSelection"))
            self.cover_preview.set_card(None)
            self._baseline = None
            self._dirty = False
            self._setting_card = False
            self._sync_detail_state()
            self._reset_scroll_positions()
            return

        self.character_name.setText(card.identity.character_name)
        self.display_name.setText(card.identity.display_name)
        self.aliases.set_values(card.identity.aliases)
        self.tags.set_values(card.user_metadata.tags)
        self.notes.setPlainText(card.user_metadata.notes)
        self._set_compile_variant(card.user_metadata.compile_variant)
        dialogue_count = card.user_metadata.extra_dialogue_count
        self.extra_dialogue_count.setText("" if dialogue_count is None else str(dialogue_count))
        self.compile_requirements.setPlainText(card.user_metadata.compile_requirements)
        self.cover_preview.set_card(card)
        self._baseline = self._editable_snapshot_from_ui()
        self._dirty = False
        self._setting_card = False
        self._sync_detail_state()
        self._reset_scroll_positions()

    def apply_to_card(self, card: CharacterCard) -> CharacterCard:
        output = card.model_copy(deep=True)
        original = _editable_snapshot(output)
        output.identity.character_name = self.character_name.text().strip()
        output.identity.display_name = self.display_name.text().strip()
        output.identity.aliases = self.aliases.values()
        output.user_metadata.tags = self.tags.values()
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

    def is_dirty(self) -> bool:
        return self._dirty

    def is_result_stale(self) -> bool:
        if self._card is None:
            return False
        return self._dirty or self._card.compile_status == CharacterCardStatus.STALE

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            panel = CHARACTER_CARD_DARK_PANEL
            panel_alt = CHARACTER_CARD_DARK_PANEL_ALT
            border = CHARACTER_CARD_DARK_BORDER
            text = CHARACTER_CARD_DARK_TEXT
            muted = CHARACTER_CARD_DARK_MUTED_TEXT
        else:
            panel = CHARACTER_CARD_LIGHT_PANEL
            panel_alt = CHARACTER_CARD_LIGHT_PANEL_ALT
            border = CHARACTER_CARD_LIGHT_BORDER
            text = CHARACTER_CARD_LIGHT_TEXT
            muted = CHARACTER_CARD_LIGHT_MUTED_TEXT
        self.setStyleSheet(
            f"""
            CardWidget {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QWidget#editorContent, QWidget#inspectorContent {{
                background: transparent;
            }}
            QLabel#sectionHelper, QLabel#mutedLabel {{
                color: {muted};
            }}
            QLabel#summaryChip, QLabel#statusBadge {{
                border-radius: 7px;
                padding: 2px 8px;
            }}
            QLabel#summaryChip {{
                color: {text};
                background: {panel_alt};
                border: 1px solid {border};
            }}
            QLabel#coverPreview {{
                color: {muted};
                border: 1px dashed {border};
                border-radius: 8px;
                background: {panel_alt};
            }}
            PushButton#dangerButton {{
                color: {CHARACTER_CARD_DANGER};
                border: 1px solid rgba(230, 106, 106, 0.55);
                background: rgba(230, 106, 106, 0.08);
            }}
            """
        )
        for label in self._muted_labels:
            label.setStyleSheet(f"color: {muted};")
        for editor in (self.aliases, self.tags):
            editor.apply_theme_colors()
        self._sync_detail_state()

    def _build_editor(self) -> None:
        self.editor_content.setObjectName("editorContent")
        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(StrongBodyLabel(t("cards.detail.title"), self.editor_content))

        self.status_label = CaptionLabel(t("cards.status.noSelection"), self.editor_content)
        self.status_label.setWordWrap(True)
        self.summary_chip_panel = QWidget(self.editor_content)
        self.summary_chip_flow = FlowLayout(self.summary_chip_panel, spacing=6)
        self.summary_chip_panel.setLayout(self.summary_chip_flow)
        self.summary_chips: dict[str, QLabel] = {}
        for key in ("status", "source", "revision", "format"):
            chip = QLabel("", self.editor_content)
            chip.setObjectName("summaryChip")
            chip.setWordWrap(False)
            chip.setMaximumWidth(240)
            self.summary_chips[key] = chip
            self.summary_chip_flow.addWidget(chip)
        header.addWidget(self.summary_chip_panel)
        header.addWidget(self.status_label)
        self.editor_layout.addLayout(header)

        self.character_name = LineEdit(self.editor_content)
        self.character_name.setPlaceholderText(t("cards.field.characterName.placeholder"))
        self.display_name = LineEdit(self.editor_content)
        self.display_name.setPlaceholderText(t("cards.field.displayName.placeholder"))
        for field in (self.character_name, self.display_name):
            field.setMinimumHeight(36)
        self.aliases = ChipTagEditor(
            self.editor_content,
            placeholder=t("cards.field.aliases.placeholder"),
            add_text=t("cards.chip.addAlias"),
        )
        self.tags = ChipTagEditor(
            self.editor_content,
            placeholder=t("cards.field.tags.placeholder"),
            add_text=t("cards.chip.addTag"),
        )

        identity_card, identity_layout = _make_card(self.editor_content, t("cards.detail.identity"))
        self.identity_grid = QGridLayout()
        self.identity_grid.setContentsMargins(0, 0, 0, 0)
        self.identity_grid.setHorizontalSpacing(14)
        self.identity_grid.setVerticalSpacing(12)
        self.character_name_field = _field_stack_widget(
            t("cards.field.characterName"),
            self.character_name,
            identity_card,
        )
        self.display_name_field = _field_stack_widget(
            t("cards.field.displayName"),
            self.display_name,
            identity_card,
        )
        self.identity_grid.addWidget(self.character_name_field, 0, 0)
        self.identity_grid.addWidget(self.display_name_field, 0, 1)
        self.identity_grid.setColumnStretch(0, 1)
        self.identity_grid.setColumnStretch(1, 1)
        identity_layout.addLayout(self.identity_grid)
        identity_layout.addWidget(_field_title(t("cards.field.aliases"), identity_card))
        identity_layout.addWidget(self.aliases)
        identity_layout.addWidget(_field_title(t("cards.field.tags"), identity_card))
        identity_layout.addWidget(self.tags)
        self.editor_layout.addWidget(identity_card)

        self.notes = PlainTextEdit(self.editor_content)
        self.notes.setFixedHeight(86)
        self.notes.setPlaceholderText(t("cards.field.notes.placeholder"))
        self.compile_requirements = PlainTextEdit(self.editor_content)
        self.compile_requirements.setFixedHeight(86)
        self.compile_requirements.setPlaceholderText(t("cards.field.compileRequirements.placeholder"))

        ai_card, ai_layout = _make_card(self.editor_content, t("cards.section.aiInput"))
        ai_layout.addLayout(
            _textarea_block(
                t("cards.field.notes"),
                t("cards.field.notes.helper"),
                self.notes,
                self.editor_content,
            )
        )
        self.notes_counter = CaptionLabel("", self.editor_content)
        self.notes_counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        ai_layout.addWidget(self.notes_counter)
        ai_layout.addLayout(
            _textarea_block(
                t("cards.field.compileRequirements"),
                t("cards.field.compileRequirements.helper"),
                self.compile_requirements,
                self.editor_content,
            )
        )
        self.requirements_counter = CaptionLabel("", self.editor_content)
        self.requirements_counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        ai_layout.addWidget(self.requirements_counter)
        self.editor_layout.addWidget(ai_card)

        self.compile_variant = ComboBox(self.editor_content)
        for variant in COMPILE_VARIANTS:
            self.compile_variant.addItem(t(f"cards.compileVariant.{variant.value}"))
        self.extra_dialogue_count = LineEdit(self.editor_content)
        self.extra_dialogue_count.setValidator(QIntValidator(0, 100, self.extra_dialogue_count))
        self.extra_dialogue_count.setPlaceholderText(t("cards.field.extraDialogueCount.placeholder"))
        self.compile_variant.setMinimumHeight(36)
        self.extra_dialogue_count.setMinimumHeight(36)
        self.export_astrbot_after_compile = CheckBox(
            t("cards.option.exportAstrbotAfterCompile"),
            self.editor_content,
        )

        output_card, output_layout = _make_card(self.editor_content, t("cards.section.outputSettings"))
        self.output_grid = QGridLayout()
        self.output_grid.setContentsMargins(0, 0, 0, 0)
        self.output_grid.setHorizontalSpacing(14)
        self.output_grid.setVerticalSpacing(12)
        self.compile_variant_field = _field_stack_widget(
            t("cards.field.compileVariant"),
            self.compile_variant,
            output_card,
        )
        self.extra_dialogue_count_field = _field_stack_widget(
            t("cards.field.extraDialogueCount"),
            self.extra_dialogue_count,
            output_card,
        )
        self.output_grid.addWidget(self.compile_variant_field, 0, 0)
        self.output_grid.addWidget(self.extra_dialogue_count_field, 0, 1)
        self.output_grid.setColumnStretch(0, 1)
        self.output_grid.setColumnStretch(1, 1)
        output_layout.addLayout(self.output_grid)
        output_layout.addWidget(self.export_astrbot_after_compile)
        hint = CaptionLabel(t("cards.outputSettings.hint"), output_card)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        output_layout.addWidget(hint)
        self.editor_layout.addWidget(output_card)
        self.editor_layout.addStretch(1)

        self._muted_labels = [self.status_label, self.notes_counter, self.requirements_counter, hint]

    def _build_inspector(self) -> None:
        self.inspector_content.setObjectName("inspectorContent")

        cover_card, cover_layout = _make_card(self.inspector_content, t("cards.inspector.cover"))
        cover_row = QHBoxLayout()
        cover_row.setContentsMargins(0, 0, 0, 0)
        cover_row.addStretch(1)
        self.cover_preview = CoverPreviewLabel(self.inspector_content)
        cover_row.addWidget(self.cover_preview)
        cover_row.addStretch(1)
        cover_layout.addLayout(cover_row)
        cover_actions = QHBoxLayout()
        cover_actions.setContentsMargins(0, 0, 0, 0)
        cover_actions.setSpacing(8)
        self.cover_button = PushButton(t("cards.action.cover"), self.inspector_content)
        self.clear_cover_button = PushButton(t("cards.action.clearCover"), self.inspector_content)
        for button in (self.cover_button, self.clear_cover_button):
            button.setMinimumHeight(34)
        cover_actions.addWidget(self.cover_button, 1)
        cover_actions.addWidget(self.clear_cover_button, 1)
        cover_layout.addLayout(cover_actions)
        self.inspector_layout.addWidget(cover_card)

        status_card, status_layout = _make_card(self.inspector_content, t("cards.inspector.status"))
        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(8)
        self.status_values: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(
            (
                ("edit", t("cards.status.editState")),
                ("compile", t("cards.status.compileState")),
                ("source", t("cards.status.source")),
                ("revision", t("cards.status.revision")),
                ("compiledAt", t("cards.status.lastCompile")),
            )
        ):
            status_grid.addWidget(CaptionLabel(label, status_card), row, 0)
            value = BodyLabel("-", status_card)
            value.setWordWrap(True)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.status_values[key] = value
            status_grid.addWidget(value, row, 1)
        status_grid.setColumnStretch(1, 1)
        status_layout.addLayout(status_grid)
        self.inspector_layout.addWidget(status_card)

        quick_card, quick_layout = _make_card(self.inspector_content, t("cards.inspector.quickActions"))
        quick_row = QHBoxLayout()
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.setSpacing(8)
        self.save_button = PrimaryPushButton(t("cards.action.save"), self.inspector_content)
        self.preview_button = PushButton(t("cards.action.previewResult"), self.inspector_content)
        for button in (self.save_button, self.preview_button):
            button.setMinimumHeight(36)
        quick_row.addWidget(self.save_button, 1)
        quick_row.addWidget(self.preview_button, 1)
        quick_layout.addLayout(quick_row)
        self.stale_warning_label = CaptionLabel(t("cards.preview.staleHint"), self.inspector_content)
        self.stale_warning_label.setWordWrap(True)
        quick_layout.addWidget(self.stale_warning_label)
        self.compile_button = PrimaryPushButton(t("cards.action.compile"), self.inspector_content)
        self.compile_button.setMinimumHeight(36)
        quick_layout.addWidget(self.compile_button)
        self.inspector_layout.addWidget(quick_card)

        output_card, output_layout = _make_card(self.inspector_content, t("cards.inspector.outputActions"))
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        self.export_button = PushButton(t("cards.action.export"), self.inspector_content)
        self.astrbot_button = PushButton(t("cards.action.astrbotHelper"), self.inspector_content)
        for button in (self.export_button, self.astrbot_button):
            button.setMinimumHeight(36)
        output_row.addWidget(self.export_button, 1)
        output_row.addWidget(self.astrbot_button, 1)
        output_layout.addLayout(output_row)
        self.inspector_layout.addWidget(output_card)

        danger_card, danger_layout = _make_card(self.inspector_content, t("cards.inspector.dangerActions"))
        self.delete_button = PushButton(t("cards.action.deleteCard"), self.inspector_content)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setMinimumHeight(36)
        danger_layout.addWidget(self.delete_button)
        self.inspector_layout.addWidget(danger_card)
        self.inspector_layout.addStretch(1)

        self.save_button.clicked.connect(self.saveRequested)
        self.cover_button.clicked.connect(self.coverRequested)
        self.clear_cover_button.clicked.connect(self.clearCoverRequested)
        self.preview_button.clicked.connect(self.previewRequested)
        self.compile_button.clicked.connect(self.compileRequested)
        self.export_button.clicked.connect(self.exportRequested)
        self.astrbot_button.clicked.connect(self.astrbotRequested)
        self.delete_button.clicked.connect(self.deleteRequested)
        self._muted_labels.extend([self.stale_warning_label])

    def _connect_dirty_signals(self) -> None:
        self.character_name.textChanged.connect(self._sync_dirty_state)
        self.display_name.textChanged.connect(self._sync_dirty_state)
        self.aliases.valuesChanged.connect(self._sync_dirty_state)
        self.tags.valuesChanged.connect(self._sync_dirty_state)
        self.notes.textChanged.connect(self._on_text_changed)
        self.compile_variant.currentIndexChanged.connect(self._sync_dirty_state)
        self.extra_dialogue_count.textChanged.connect(self._sync_dirty_state)
        self.compile_requirements.textChanged.connect(self._on_text_changed)
        self.export_astrbot_after_compile.stateChanged.connect(self._sync_compile_button)

    def _on_text_changed(self) -> None:
        self._update_text_counters()
        self._sync_dirty_state()

    def _sync_dirty_state(self) -> None:
        if self._setting_card:
            return
        self._dirty = self._baseline is not None and self._editable_snapshot_from_ui() != self._baseline
        self._sync_detail_state()

    def _sync_detail_state(self) -> None:
        self._update_text_counters()
        self._sync_summary_chips()
        self._sync_status_card()
        self._sync_compile_button()
        self.stale_warning_label.setVisible(self.is_result_stale())

    def _sync_summary_chips(self) -> None:
        card = self._card
        if card is None:
            for chip in self.summary_chips.values():
                chip.hide()
            return
        self.status_label.setText("")
        values = {
            "status": t("cards.summaryChip.status", value=_status_display(card, self._dirty)),
            "source": t("cards.summaryChip.source", value=card.compile_source.value),
            "revision": t("cards.summaryChip.revision", value=card.revision),
            "format": t(
                "cards.summaryChip.format",
                value=t(f"cards.compileVariant.{self._current_compile_variant().value}"),
            ),
        }
        for key, value in values.items():
            chip = self.summary_chips[key]
            chip.setText(_elide_text(value, 28))
            chip.setToolTip(value)
            chip.show()

    def _sync_status_card(self) -> None:
        card = self._card
        if card is None:
            for value in self.status_values.values():
                value.setText("-")
            return
        self.status_values["edit"].setText(
            t("cards.status.unsaved") if self._dirty else t("cards.status.saved")
        )
        self.status_values["compile"].setText(_status_display(card, self._dirty))
        self.status_values["source"].setText(card.compile_source.value)
        self.status_values["revision"].setText(str(card.revision))
        self.status_values["compiledAt"].setText(
            card.compiled_at.strftime("%Y-%m-%d %H:%M") if card.compiled_at else "-"
        )

    def _sync_compile_button(self) -> None:
        if self._card is None:
            self.compile_button.setText(t("cards.action.compile"))
            return
        if self._dirty:
            self.compile_button.setText(t("cards.action.saveAndCompile"))
        elif self._card.compile_status in (CharacterCardStatus.COMPILED, CharacterCardStatus.STALE):
            self.compile_button.setText(t("cards.action.recompile"))
        else:
            self.compile_button.setText(t("cards.action.compileOnly"))

    def _update_text_counters(self) -> None:
        if not hasattr(self, "notes_counter"):
            return
        self.notes_counter.setText(
            t("cards.textCounter", count=len(self.notes.toPlainText()), limit=TEXT_LIMIT)
        )
        self.requirements_counter.setText(
            t("cards.textCounter", count=len(self.compile_requirements.toPlainText()), limit=TEXT_LIMIT)
        )

    def _editable_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.character_name,
            self.display_name,
            self.aliases,
            self.tags,
            self.notes,
            self.compile_variant,
            self.extra_dialogue_count,
            self.compile_requirements,
            self.export_astrbot_after_compile,
        )

    def _action_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.save_button,
            self.cover_button,
            self.clear_cover_button,
            self.preview_button,
            self.compile_button,
            self.export_button,
            self.astrbot_button,
            self.delete_button,
        )

    def _clear_fields(self) -> None:
        self.character_name.clear()
        self.display_name.clear()
        self.aliases.clear()
        self.tags.clear()
        self.notes.clear()
        self._set_compile_variant(CharacterCardCompileVariant.GENERAL)
        self.extra_dialogue_count.clear()
        self.compile_requirements.clear()

    def _reset_scroll_positions(self) -> None:
        def reset() -> None:
            self.editor_scroll.verticalScrollBar().setValue(0)
            self.inspector_scroll.verticalScrollBar().setValue(0)

        QTimer.singleShot(0, reset)

    def _editable_snapshot_from_ui(self) -> tuple[object, ...]:
        return (
            self.character_name.text().strip(),
            self.display_name.text().strip(),
            tuple(self.aliases.values()),
            tuple(self.tags.values()),
            self.notes.toPlainText().strip(),
            self._current_compile_variant(),
            _optional_dialogue_count(self.extra_dialogue_count.text()),
            self.compile_requirements.toPlainText().strip(),
        )

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


class CoverPreviewLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = ""
        self.setObjectName("coverPreview")
        self.setFixedSize(72, 128)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)

    def set_card(self, card: CharacterCard | None) -> None:
        self._path = store.cover_path_for_card(card) if card is not None else ""
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        pixmap = QPixmap()
        if self._path and Path(self._path).exists():
            pixmap = QPixmap(self._path)
        if pixmap.isNull():
            self.clear()
            self.setText(t("cards.cover.placeholder"))
            return
        self.setText("")
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def _make_scroll_area(parent: QWidget) -> QScrollArea:
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


def _make_card(parent: QWidget, title: str) -> tuple[CardWidget, QVBoxLayout]:
    card = CardWidget(parent)
    card.setBorderRadius(8)
    card.setMinimumWidth(0)
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(8)
    layout.addWidget(StrongBodyLabel(title, card))
    return card, layout


def _field_stack_widget(label_text: str, widget: QWidget, parent: QWidget) -> QWidget:
    container = QWidget(parent)
    container.setMinimumWidth(0)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(_field_title(label_text, container))
    layout.addWidget(widget)
    return container


def _add_field_stack(layout: QGridLayout, row: int, column: int, label_text: str, widget: QWidget) -> None:
    stack = QVBoxLayout()
    stack.setContentsMargins(0, 0, 0, 0)
    stack.setSpacing(6)
    stack.addWidget(_field_title(label_text, widget.parentWidget()))
    stack.addWidget(widget)
    layout.addLayout(stack, row, column)


def _textarea_block(title: str, helper: str, editor: PlainTextEdit, parent: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(8)
    title_row.addWidget(_field_title(title, parent))
    helper_label = CaptionLabel(helper, parent)
    helper_label.setObjectName("sectionHelper")
    helper_label.setWordWrap(True)
    title_row.addWidget(helper_label, 1)
    layout.addLayout(title_row)
    layout.addWidget(editor)
    return layout


def _field_title(text: str, parent: QWidget | None) -> CaptionLabel:
    label = CaptionLabel(text, parent)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


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


def _optional_dialogue_count(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return max(0, min(100, int(text)))
    except ValueError:
        return None


def _status_display(card: CharacterCard, dirty: bool = False) -> str:
    if dirty and card.compile_status == CharacterCardStatus.COMPILED:
        return t("cards.status.display.stale")
    if card.compile_status == CharacterCardStatus.STALE:
        return t("cards.status.display.stale")
    if card.compile_status in (CharacterCardStatus.EMPTY, CharacterCardStatus.DRAFT):
        return t("cards.status.display.uncompiled")
    return t(f"cards.status.display.{card.compile_status.value}")


def _elide_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: max(0, maximum - 3)].rstrip() + "..."
