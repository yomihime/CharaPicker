from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, PlainTextEdit, PushButton, SubtitleLabel


class OutputPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("outputPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("生成输出", self))
        header.addStretch(1)
        header.addWidget(PushButton("导出 Markdown", self))
        root.addLayout(header)

        card = CardWidget(self)
        card.setBorderRadius(8)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)

        self.preview = PlainTextEdit(card)
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("角色卡、设定稿或知识库摘要会显示在这里。")
        layout.addWidget(self.preview)
        root.addWidget(card, 1)

    def set_markdown(self, text: str) -> None:
        self.preview.setPlainText(text)
