from __future__ import annotations

import json

from PyQt6.QtWidgets import QTabWidget, QTextBrowser, QWidget
from qfluentwidgets import PlainTextEdit

from core.character_card_formats import to_astrbot_copy_markdown, to_character_card_v2_json
from core.character_card_renderers import build_human_json_sections, render_card_html, render_card_markdown
from core.models import CharacterCard
from gui.widgets.dialog_middleware import FluentDialog
from gui.widgets.human_json_view import HumanJsonView
from utils.i18n import t


class CharacterCardPreviewDialog(FluentDialog):
    def __init__(self, card: CharacterCard, parent: QWidget | None = None, *, preview_only: bool = False) -> None:
        super().__init__(
            t("cards.preview.title"),
            parent,
            width=820,
            height=620,
            margins=(18, 16, 18, 18),
            spacing=10,
        )
        self.card = card
        tabs = QTabWidget(self.dialog_card)
        self.content_layout.addWidget(tabs, 1)

        html_view = QTextBrowser(tabs)
        html_view.setOpenExternalLinks(False)
        html_view.setHtml(render_card_html(card))
        tabs.addTab(html_view, t("cards.preview.tab.html"))

        markdown_text = render_card_markdown(card)
        markdown = QTextBrowser(tabs)
        markdown.setOpenExternalLinks(False)
        markdown.setMarkdown(markdown_text)
        tabs.addTab(markdown, t("cards.preview.tab.markdown"))

        markdown_source = PlainTextEdit(tabs)
        markdown_source.setReadOnly(True)
        markdown_source.setPlainText(markdown_text)
        tabs.addTab(markdown_source, t("cards.preview.tab.markdownSource"))

        json_view = HumanJsonView(tabs)
        json_view.set_sections(build_human_json_sections(card))
        tabs.addTab(json_view, t("cards.preview.tab.json"))

        astrbot = PlainTextEdit(tabs)
        astrbot.setReadOnly(True)
        astrbot.setPlainText(str(to_astrbot_copy_markdown(card).payload))
        tabs.addTab(astrbot, t("cards.preview.tab.astrbot"))

        card_v2 = PlainTextEdit(tabs)
        card_v2.setReadOnly(True)
        card_v2.setPlainText(json.dumps(to_character_card_v2_json(card).payload, ensure_ascii=False, indent=2))
        tabs.addTab(card_v2, t("cards.preview.tab.v2"))

        if preview_only:
            self.title_label.setText(t("cards.preview.previewOnlyTitle"))
