from __future__ import annotations

from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, ComboBox, LineEdit, SubtitleLabel, SwitchButton


class SettingsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(SubtitleLabel("设置", self))

        card = CardWidget(self)
        card.setBorderRadius(8)
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setSpacing(12)

        self.model_path = LineEdit(card)
        self.model_path.setPlaceholderText("models/...")

        self.runner_combo = ComboBox(card)
        self.runner_combo.addItems(["本地模型", "OpenAI Compatible", "手动导入 JSON"])

        self.use_cache = SwitchButton(card)
        self.use_cache.setChecked(True)

        form.addRow("模型路径", self.model_path)
        form.addRow("推理后端", self.runner_combo)
        form.addRow("使用缓存", self.use_cache)
        root.addWidget(card)
        root.addStretch(1)
