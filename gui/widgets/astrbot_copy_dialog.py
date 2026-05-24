from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, PlainTextEdit, PushButton

from core.character_card_formats import to_astrbot_copy_sections
from core.models import CharacterCard
from gui.widgets.dialog_middleware import FluentDialog
from utils.i18n import t


class AstrBotCopyDialog(FluentDialog):
    def __init__(self, card: CharacterCard, parent: QWidget | None = None) -> None:
        super().__init__(
            t("cards.astrbot.dialog.title"),
            parent,
            width=760,
            height=620,
            margins=(18, 16, 18, 18),
            spacing=10,
        )
        formatted = to_astrbot_copy_sections(card)
        payload = formatted.payload if isinstance(formatted.payload, dict) else {}

        description = CaptionLabel(t("cards.astrbot.dialog.description"), self.dialog_card)
        description.setWordWrap(True)
        self.content_layout.addWidget(description)

        scroll = QScrollArea(self.dialog_card)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self._add_text_section(
            content_layout,
            t("cards.astrbot.field.name"),
            str(payload.get("name", "")),
            compact=True,
        )
        self._add_text_section(
            content_layout,
            t("cards.astrbot.field.systemPrompt"),
            str(payload.get("system_prompt", "")),
        )
        self._add_text_section(
            content_layout,
            t("cards.astrbot.field.errorReply"),
            str(payload.get("custom_error_reply", "")),
            empty_text=t("cards.astrbot.optional.empty"),
            compact=True,
        )

        dialogues = payload.get("preset_dialogues", [])
        if isinstance(dialogues, list) and dialogues:
            for index, item in enumerate(dialogues, start=1):
                if not isinstance(item, dict):
                    continue
                text = "\n".join(
                    part
                    for part in [
                        f"User: {item.get('user', '')}",
                        f"Assistant: {item.get('assistant', '')}",
                    ]
                    if part.strip()
                )
                self._add_text_section(
                    content_layout,
                    t("cards.astrbot.field.dialogue", index=index),
                    text,
                    compact=True,
                )
        else:
            self._add_text_section(
                content_layout,
                t("cards.astrbot.field.presetDialogues"),
                "",
                empty_text=t("cards.astrbot.dialogues.empty"),
                compact=True,
            )

        scroll.setWidget(content)
        self.content_layout.addWidget(scroll, 1)

    def _add_text_section(
        self,
        layout: QVBoxLayout,
        title: str,
        text: str,
        *,
        empty_text: str | None = None,
        compact: bool = False,
    ) -> None:
        value = text.strip()
        visible_text = value or (empty_text or t("cards.astrbot.empty"))

        header = QHBoxLayout()
        header.addWidget(BodyLabel(title, self.dialog_card))
        header.addStretch(1)
        copy_button = PushButton(t("cards.astrbot.copy"), self.dialog_card)
        copy_button.setEnabled(bool(value))
        copy_button.clicked.connect(lambda _checked=False, payload=value: self._copy_text(payload))
        header.addWidget(copy_button)
        layout.addLayout(header)

        editor = PlainTextEdit(self.dialog_card)
        editor.setReadOnly(True)
        editor.setPlainText(visible_text)
        editor.setFixedHeight(72 if compact else 190)
        layout.addWidget(editor)

    def _copy_text(self, text: str) -> None:
        QApplication.clipboard().setText(text)
