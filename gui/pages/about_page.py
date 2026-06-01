from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    HyperlinkButton,
    PlainTextEdit,
    PushButton,
    SubtitleLabel,
    TitleLabel,
)

from gui.widgets.dialog_middleware import FluentDialog
from utils.i18n import t
from utils.paths import APP_ROOT


class LicenseDialog(FluentDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            t("about.license.dialog.title"),
            parent,
            width=780,
            height=640,
            margins=(20, 18, 20, 20),
            spacing=10,
        )

        description = CaptionLabel(t("about.license.dialog.description"), self.dialog_card)
        description.setWordWrap(True)
        self.content_layout.addWidget(description)

        self.license_text = _build_license_text()
        editor = PlainTextEdit(self.dialog_card)
        editor.setReadOnly(True)
        editor.setPlainText(self.license_text)
        self.content_layout.addWidget(editor, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        copy_button = PushButton(t("about.license.copy"), self.dialog_card)
        copy_button.clicked.connect(self._copy_license_text)
        actions.addWidget(copy_button)

        close_button = PushButton(t("about.license.close"), self.dialog_card)
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        self.content_layout.addLayout(actions)

    def _copy_license_text(self) -> None:
        QApplication.clipboard().setText(self.license_text)


def _build_license_text() -> str:
    summary = "\n".join(
        [
            f"- {t('about.license.source')}",
            f"- {t('about.license.thirdParty')}",
            f"- {t('about.license.binaryDistribution')}",
        ]
    )
    sections = [
        (t("about.license.section.summary"), summary),
        (t("about.license.section.license"), _read_notice_file("LICENSE")),
        (
            t("about.license.section.thirdParty"),
            _read_notice_file("THIRD_PARTY_NOTICES.md"),
        ),
    ]
    return "\n\n".join(f"{title}\n{'=' * len(title)}\n{body}" for title, body in sections)


def _read_notice_file(file_name: str) -> str:
    path = APP_ROOT / file_name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return t("about.license.fileMissing", file=file_name)


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
        links.addWidget(
            HyperlinkButton(
                "https://github.com/yomihime/CharaPicker",
                t("about.links.home"),
                links_card,
            )
        )
        links.addWidget(HyperlinkButton("https://qfluentwidgets.com/", "QFluentWidgets", links_card))
        links.addWidget(
            HyperlinkButton(
                "https://www.riverbankcomputing.com/software/pyqt/",
                "PyQt",
                links_card,
            )
        )
        links_layout.addLayout(links)
        root.addWidget(links_card)

        license_row = QHBoxLayout()
        license_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        license_button = PushButton(t("about.license.button"), self)
        license_button.setObjectName("licenseButton")
        license_button.setMinimumWidth(150)
        license_button.setFixedHeight(30)
        license_button.setStyleSheet("PushButton#licenseButton { padding: 1px 24px; }")
        license_button.clicked.connect(self._show_license_dialog)
        license_row.addWidget(license_button)
        root.addLayout(license_row)

        root.addStretch(1)

    def _show_license_dialog(self) -> None:
        LicenseDialog(self).exec()
