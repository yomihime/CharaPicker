from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, HyperlinkButton, SubtitleLabel, TitleLabel

from utils.i18n import t


class AboutPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        root.addWidget(SubtitleLabel(t("about.title"), self))

        product_card = CardWidget(self)
        product_card.setBorderRadius(8)
        product_layout = QVBoxLayout(product_card)
        product_layout.setContentsMargins(20, 18, 20, 20)
        product_layout.setSpacing(10)
        product_layout.addWidget(TitleLabel(t("about.product"), product_card))

        description = BodyLabel(
            t("about.description"),
            product_card,
        )
        description.setWordWrap(True)
        product_layout.addWidget(description)
        product_layout.addWidget(BodyLabel(t("about.version"), product_card))
        root.addWidget(product_card)

        notice_card = CardWidget(self)
        notice_card.setBorderRadius(8)
        notice_layout = QVBoxLayout(notice_card)
        notice_layout.setContentsMargins(20, 18, 20, 20)
        notice_layout.setSpacing(10)
        notice_layout.addWidget(SubtitleLabel(t("about.notice.title"), notice_card))

        notices = [
            t("about.notice.legalMaterial"),
            t("about.notice.review"),
            t("about.notice.copyright"),
            t("about.notice.thirdParty"),
        ]
        for notice in notices:
            label = BodyLabel(f"- {notice}", notice_card)
            label.setWordWrap(True)
            notice_layout.addWidget(label)
        root.addWidget(notice_card)

        links_card = CardWidget(self)
        links_card.setBorderRadius(8)
        links_layout = QVBoxLayout(links_card)
        links_layout.setContentsMargins(20, 18, 20, 20)
        links_layout.setSpacing(10)
        links_layout.addWidget(SubtitleLabel(t("about.links.title"), links_card))

        links = QHBoxLayout()
        links.setAlignment(Qt.AlignmentFlag.AlignLeft)
        links.addWidget(HyperlinkButton("https://github.com/", t("about.links.home"), links_card))
        links.addWidget(HyperlinkButton("https://qfluentwidgets.com/", "QFluentWidgets", links_card))
        links.addWidget(HyperlinkButton("https://www.riverbankcomputing.com/software/pyqt/", "PyQt", links_card))
        links_layout.addLayout(links)
        root.addWidget(links_card)

        root.addStretch(1)
