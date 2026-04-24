from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, ScrollArea, StrongBodyLabel

from core.models import InsightStatus


STATUS_TEXT = {
    InsightStatus.QUEUED.value: "等待",
    InsightStatus.RUNNING.value: "进行中",
    InsightStatus.DONE.value: "完成",
    InsightStatus.WARNING.value: "注意",
}

STATUS_COLOR = {
    InsightStatus.QUEUED.value: "#8A8F98",
    InsightStatus.RUNNING.value: "#0078D4",
    InsightStatus.DONE.value: "#107C10",
    InsightStatus.WARNING.value: "#C19C00",
}


class TimelineMarker(QLabel):
    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setStyleSheet(
            "border-radius: 6px;"
            f"background: {color};"
        )


class InsightCard(CardWidget):
    def __init__(self, event: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        status = event.get("status", InsightStatus.QUEUED.value)
        color = STATUS_COLOR.get(status, STATUS_COLOR[InsightStatus.QUEUED.value])

        self.setBorderRadius(8)
        self.setMinimumHeight(92)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        timeline = QVBoxLayout()
        timeline.setContentsMargins(0, 4, 0, 4)
        timeline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        timeline.addWidget(TimelineMarker(color))

        line = QFrame(self)
        line.setFixedWidth(2)
        line.setStyleSheet(f"background: {color}; border: none;")
        timeline.addWidget(line, 1)
        layout.addLayout(timeline)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)

        header = QHBoxLayout()
        title = StrongBodyLabel(event.get("title", "未命名洞察"), self)
        status_label = CaptionLabel(STATUS_TEXT.get(status, "等待"), self)
        status_label.setStyleSheet(f"color: {color};")
        header.addWidget(title, 1)
        header.addWidget(status_label, 0, Qt.AlignmentFlag.AlignRight)

        description = BodyLabel(event.get("description", ""), self)
        description.setWordWrap(True)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        content.addLayout(header)
        content.addWidget(description)
        layout.addLayout(content, 1)


class InsightStreamPanel(ScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self.container = QWidget(self)
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(4, 4, 12, 4)
        self.layout.setSpacing(10)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.empty_label = BodyLabel("点击预览后，AI 洞察流会在这里逐步出现。", self.container)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(220)
        self.layout.addWidget(self.empty_label)

        self.setWidget(self.container)

    def append_event(self, event: dict) -> None:
        if self.empty_label.isVisible():
            self.empty_label.hide()
        self.layout.addWidget(InsightCard(event, self.container))

    def clear_events(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.empty_label = BodyLabel("点击预览后，AI 洞察流会在这里逐步出现。", self.container)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(220)
        self.layout.addWidget(self.empty_label)
