from __future__ import annotations

import json

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QTabWidget, QTextBrowser, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, PlainTextEdit, PushButton

from core.character_card_formats import to_astrbot_copy_markdown, to_character_card_v2_json
from core.character_card_renderers import build_human_json_sections, render_card_html, render_card_markdown
from core.models import CharacterCard
from gui.widgets.dialog_middleware import FluentDialog
from gui.widgets.human_json_view import HumanJsonView
from utils.i18n import t


class CharacterCardPreviewDialog(FluentDialog):
    def __init__(
        self,
        card: CharacterCard,
        parent: QWidget | None = None,
        *,
        preview_only: bool = False,
        stale: bool = False,
    ) -> None:
        super().__init__(
            t("cards.preview.title"),
            parent,
            width=820,
            height=620,
            margins=(18, 16, 18, 18),
            spacing=10,
        )
        self.card = card
        if stale:
            warning = CaptionLabel(t("cards.preview.staleHint"), self.dialog_card)
            warning.setWordWrap(True)
            self.content_layout.addWidget(warning)

        tabs = QTabWidget(self.dialog_card)
        self.content_layout.addWidget(tabs, 1)

        html_view = QTextBrowser(tabs)
        html_view.setOpenExternalLinks(False)
        html_view.setHtml(render_card_html(card))
        html_view.setStyleSheet(
            """
            QTextBrowser {
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 8px;
                background: #f7f6f2;
            }
            """
        )
        tabs.addTab(html_view, t("cards.preview.tab.html"))

        markdown_text = render_card_markdown(card)
        markdown = QTextBrowser(tabs)
        markdown.setOpenExternalLinks(False)
        markdown.setMarkdown(markdown_text)
        tabs.addTab(markdown, t("cards.preview.tab.markdown"))

        markdown_source = PlainTextEdit(tabs)
        markdown_source.setReadOnly(True)
        markdown_source.setPlainText(markdown_text)
        tabs.addTab(
            _source_tab(t("cards.preview.copyMarkdown"), markdown_text, markdown_source, tabs),
            t("cards.preview.tab.markdownSource"),
        )

        json_source = card.model_dump_json(indent=2)
        json_tab = QWidget(tabs)
        json_layout = QVBoxLayout(json_tab)
        json_layout.setContentsMargins(0, 0, 0, 0)
        json_layout.setSpacing(8)
        json_header = QHBoxLayout()
        json_header.addStretch(1)
        json_copy = PushButton(t("cards.preview.copyJson"), json_tab)
        json_copy.clicked.connect(lambda _checked=False: QApplication.clipboard().setText(json_source))
        json_header.addWidget(json_copy)
        json_layout.addLayout(json_header)
        json_view = HumanJsonView(json_tab)
        json_view.set_sections(build_human_json_sections(card))
        json_layout.addWidget(json_view, 1)
        tabs.addTab(json_tab, t("cards.preview.tab.json"))

        astrbot_text = str(to_astrbot_copy_markdown(card).payload)
        astrbot = PlainTextEdit(tabs)
        astrbot.setReadOnly(True)
        astrbot.setPlainText(astrbot_text)
        tabs.addTab(
            _source_tab(t("cards.preview.copyAstrBot"), astrbot_text, astrbot, tabs),
            t("cards.preview.tab.astrbot"),
        )

        card_v2_text = json.dumps(to_character_card_v2_json(card).payload, ensure_ascii=False, indent=2)
        card_v2 = PlainTextEdit(tabs)
        card_v2.setReadOnly(True)
        card_v2.setPlainText(card_v2_text)
        tabs.addTab(
            _source_tab(t("cards.preview.copyCardV2"), card_v2_text, card_v2, tabs),
            t("cards.preview.tab.v2"),
        )

        if preview_only:
            self.title_label.setText(t("cards.preview.previewOnlyTitle"))


def _source_tab(button_text: str, text: str, editor: PlainTextEdit, parent: QWidget) -> QWidget:
    tab = QWidget(parent)
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    header = QHBoxLayout()
    header.addStretch(1)
    copy_button = PushButton(button_text, tab)
    copy_button.clicked.connect(lambda _checked=False: QApplication.clipboard().setText(text))
    header.addWidget(copy_button)
    layout.addLayout(header)
    layout.addWidget(editor, 1)
    return tab
