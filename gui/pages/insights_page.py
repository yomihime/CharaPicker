from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ProgressBar, SubtitleLabel

from gui.widgets.insight_stream_panel import InsightStreamPanel


class InsightsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("insightsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("Insight Stream", self))
        title_row.addStretch(1)
        root.addLayout(title_row)

        status_card = CardWidget(self)
        status_card.setBorderRadius(8)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(18, 14, 18, 16)
        status_layout.setSpacing(8)
        status_layout.addWidget(BodyLabel("预览进度", status_card))
        self.progress = ProgressBar(status_card)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_layout.addWidget(self.progress)
        root.addWidget(status_card)

        self.stream_panel = InsightStreamPanel(self)
        root.addWidget(self.stream_panel, 1)

    def append_event(self, event: dict) -> None:
        self.stream_panel.append_event(event)

    def clear_events(self) -> None:
        self.progress.setValue(0)
        self.stream_panel.clear_events()

    def set_progress(self, value: int) -> None:
        self.progress.setValue(value)
