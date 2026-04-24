from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, ScrollArea, StrongBodyLabel, isDarkTheme

from core.models import InsightStatus
from utils.i18n import t


STATUS_TEXT = {
    InsightStatus.QUEUED.value: "insight.status.queued",
    InsightStatus.RUNNING.value: "insight.status.running",
    InsightStatus.DONE.value: "insight.status.done",
    InsightStatus.WARNING.value: "insight.status.warning",
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
        title = StrongBodyLabel(event.get("title", t("insight.untitled")), self)
        status_label = CaptionLabel(t(STATUS_TEXT.get(status, "insight.status.queued")), self)
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
        self.setObjectName("insightStreamPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(180)

        self.container = QWidget(self)
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(4, 4, 12, 4)
        self.layout.setSpacing(10)

        self.empty_label = BodyLabel(t("insight.empty"), self.container)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(160)
        self.layout.addWidget(self.empty_label, 1)
        self.layout.setAlignment(self.empty_label, Qt.AlignmentFlag.AlignCenter)

        self.setWidget(self.container)
        self.apply_theme_colors()

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

        self.empty_label = BodyLabel(t("insight.empty"), self.container)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(160)
        self.layout.addWidget(self.empty_label, 1)
        self.layout.setAlignment(self.empty_label, Qt.AlignmentFlag.AlignCenter)
        self.apply_theme_colors()

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            panel_background = "#202020"
            empty_color = "#c9c9c9"
        else:
            panel_background = "#ffffff"
            empty_color = "#5f6670"

        self.setStyleSheet(
            f"""
            ScrollArea#insightStreamPanel {{
                background: {panel_background};
                border: 1px solid {'#3d3d3d' if isDarkTheme() else '#d8dde6'};
                border-radius: 6px;
            }}
            """
        )
        self.viewport().setStyleSheet(f"background: {panel_background}; border: none;")
        self.container.setStyleSheet(f"background: {panel_background};")
        self.empty_label.setStyleSheet(f"color: {empty_color};")
