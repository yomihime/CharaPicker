from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, FluentIcon as FIF, SubtitleLabel, TransparentToolButton


class FluentDialog(QDialog):
    """Shared Fluent-style shell for app dialogs."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        width: int = 460,
        height: int = 230,
        margins: tuple[int, int, int, int] = (24, 22, 24, 22),
        spacing: int = 14,
        close_rejects: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(width, height)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.dialog_card = CardWidget(self)
        self.dialog_card.setStyleSheet("CardWidget { background-color: palette(window); }")
        self.dialog_card.setBorderRadius(8)
        self.content_layout = QVBoxLayout(self.dialog_card)
        self.content_layout.setContentsMargins(*margins)
        self.content_layout.setSpacing(spacing)

        self.header_layout = QHBoxLayout()
        self.title_label = SubtitleLabel(title, self.dialog_card)
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch(1)
        self.close_button = TransparentToolButton(FIF.CLOSE, self.dialog_card)
        self.header_layout.addWidget(self.close_button)
        self.content_layout.addLayout(self.header_layout)

        root.addWidget(self.dialog_card)
        if close_rejects:
            self.close_button.clicked.connect(self.reject)
