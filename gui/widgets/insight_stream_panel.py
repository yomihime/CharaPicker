from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, ScrollArea, StrongBodyLabel, isDarkTheme

from core.models import InsightStatus
from res.colors import (
    INSIGHT_PANEL_DARK_BACKGROUND,
    INSIGHT_PANEL_DARK_BORDER,
    INSIGHT_PANEL_DARK_EMPTY_TEXT,
    INSIGHT_PANEL_LIGHT_BACKGROUND,
    INSIGHT_PANEL_LIGHT_BORDER,
    INSIGHT_PANEL_LIGHT_EMPTY_TEXT,
    INSIGHT_STATUS_COLORS,
)
from utils.i18n import t


STATUS_TEXT = {
    InsightStatus.QUEUED.value: "insight.status.queued",
    InsightStatus.RUNNING.value: "insight.status.running",
    InsightStatus.DONE.value: "insight.status.done",
    InsightStatus.WARNING.value: "insight.status.warning",
}
AUTO_SCROLL_BOTTOM_THRESHOLD = 24
MEDIA_TYPE_LABEL_KEYS = {
    "video": "insight.mediaType.video",
    "image": "insight.mediaType.image",
    "audio": "insight.mediaType.audio",
    "text": "insight.mediaType.text",
}
CONTENT_FORM_LABEL_KEYS = {
    "unknown": "insight.contentForm.unknown",
    "anime": "insight.contentForm.anime",
    "manga": "insight.contentForm.manga",
    "novel": "insight.contentForm.novel",
    "script": "insight.contentForm.script",
    "setting_book": "insight.contentForm.settingBook",
    "audio_drama": "insight.contentForm.audioDrama",
    "video_program": "insight.contentForm.videoProgram",
    "image_set": "insight.contentForm.imageSet",
    "mixed": "insight.contentForm.mixed",
}


def _localized_meta_value(value: object, mapping: dict[str, str]) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    label_key = mapping.get(normalized)
    return t(label_key) if label_key else normalized


def _insight_meta_text(event: dict) -> str:
    meta = event.get("meta")
    if not isinstance(meta, dict):
        return ""
    parts: list[str] = []
    media_type = _localized_meta_value(meta.get("media_type"), MEDIA_TYPE_LABEL_KEYS)
    if media_type:
        parts.append(t("insight.meta.mediaType", value=media_type))
    content_form = _localized_meta_value(meta.get("content_form"), CONTENT_FORM_LABEL_KEYS)
    if content_form and content_form != t("insight.contentForm.unknown"):
        parts.append(t("insight.meta.contentForm", value=content_form))
    unit_id = str(meta.get("unit_id") or "").strip()
    if unit_id:
        parts.append(t("insight.meta.unit", value=unit_id))
    material_name = _material_display_name(meta)
    if material_name:
        parts.append(t("insight.meta.material", value=material_name))
    return t("insight.meta.separator").join(parts)


def _material_display_name(meta: dict) -> str:
    value = str(meta.get("relative_path") or meta.get("source_path") or "").strip()
    if not value:
        return ""
    return Path(value).name or value

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
        color = INSIGHT_STATUS_COLORS.get(
            status,
            INSIGHT_STATUS_COLORS[InsightStatus.QUEUED.value],
        )

        self.setBorderRadius(8)
        self.setMinimumHeight(92)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        timeline = QVBoxLayout()
        timeline.setContentsMargins(0, 4, 0, 4)
        timeline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._marker = TimelineMarker(color)
        timeline.addWidget(self._marker)

        line = QFrame(self)
        line.setFixedWidth(2)
        line.setStyleSheet(f"background: {color}; border: none;")
        timeline.addWidget(line, 1)
        layout.addLayout(timeline)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)

        header = QHBoxLayout()
        self.title_label = StrongBodyLabel(event.get("title", t("insight.untitled")), self)
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label = CaptionLabel(t(STATUS_TEXT.get(status, "insight.status.queued")), self)
        self.status_label.setStyleSheet(f"color: {color};")
        header.addWidget(self.title_label, 1)
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignRight)

        self.description_label = BodyLabel(event.get("description", ""), self)
        self.description_label.setWordWrap(True)
        self.description_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.meta_label = CaptionLabel(_insight_meta_text(event), self)
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.meta_label.setVisible(bool(self.meta_label.text()))

        content.addLayout(header)
        content.addWidget(self.description_label)
        content.addWidget(self.meta_label)
        layout.addLayout(content, 1)
        self._line = line
        self._status = status

    def update_event(self, event: dict) -> None:
        status = event.get("status", self._status)
        color = INSIGHT_STATUS_COLORS.get(
            status,
            INSIGHT_STATUS_COLORS[InsightStatus.QUEUED.value],
        )
        self._status = status
        self.title_label.setText(event.get("title", t("insight.untitled")))
        self.description_label.setText(event.get("description", ""))
        meta_text = _insight_meta_text(event)
        self.meta_label.setText(meta_text)
        self.meta_label.setVisible(bool(meta_text))
        self.status_label.setText(t(STATUS_TEXT.get(status, "insight.status.queued")))
        self.status_label.setStyleSheet(f"color: {color};")
        self._line.setStyleSheet(f"background: {color}; border: none;")
        self._marker.setStyleSheet(
            "border-radius: 6px;"
            f"background: {color};"
        )


class InsightStreamPanel(ScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("insightStreamPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(180)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget(self)
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(4, 4, 12, 4)
        self.layout.setSpacing(10)

        self.empty_label = self._create_empty_label(t("insight.empty"))
        self.layout.addWidget(self.empty_label, 1)

        self.setWidget(self.container)
        self._stream_cards: dict[str, InsightCard] = {}
        self._auto_follow_scroll = True
        scroll_bar = self.verticalScrollBar()
        scroll_bar.valueChanged.connect(self._sync_auto_follow_from_position)
        scroll_bar.rangeChanged.connect(self._schedule_scroll_to_bottom_if_following)
        self.apply_theme_colors()

    def set_empty_text_key(self, key: str) -> None:
        self.empty_label.setText(t(key))

    def append_event(self, event: dict) -> None:
        should_follow = self._auto_follow_scroll or self._is_scroll_near_bottom()
        meta = event.get("meta")
        stream_id = meta.get("stream_id") if isinstance(meta, dict) else None
        is_update = bool(meta.get("update")) if isinstance(meta, dict) else False
        if isinstance(stream_id, str) and is_update and stream_id in self._stream_cards:
            self._stream_cards[stream_id].update_event(event)
            if should_follow:
                self._schedule_scroll_to_bottom()
            return
        if self.empty_label.isVisible():
            self.empty_label.hide()
        card = InsightCard(event, self.container)
        self.layout.addWidget(card)
        if isinstance(stream_id, str):
            self._stream_cards[stream_id] = card
        if should_follow:
            self._schedule_scroll_to_bottom()

    def clear_events(self) -> None:
        self._auto_follow_scroll = True
        self._stream_cards.clear()
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.empty_label = self._create_empty_label(t("insight.empty"))
        self.layout.addWidget(self.empty_label, 1)
        self.apply_theme_colors()

    def _create_empty_label(self, text: str) -> BodyLabel:
        label = BodyLabel(text, self.container)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(160)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _is_scroll_near_bottom(self) -> bool:
        scroll_bar = self.verticalScrollBar()
        return scroll_bar.maximum() - scroll_bar.value() <= AUTO_SCROLL_BOTTOM_THRESHOLD

    def _sync_auto_follow_from_position(self, _value: int | None = None) -> None:
        self._auto_follow_scroll = self._is_scroll_near_bottom()

    def _schedule_scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, self._scroll_to_bottom_if_following)
        QTimer.singleShot(50, self._scroll_to_bottom_if_following)

    def _schedule_scroll_to_bottom_if_following(
        self,
        _minimum: int | None = None,
        _maximum: int | None = None,
    ) -> None:
        if self._auto_follow_scroll:
            self._schedule_scroll_to_bottom()

    def _scroll_to_bottom_if_following(self) -> None:
        if self._auto_follow_scroll:
            self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            panel_background = INSIGHT_PANEL_DARK_BACKGROUND
            panel_border = INSIGHT_PANEL_DARK_BORDER
            empty_color = INSIGHT_PANEL_DARK_EMPTY_TEXT
        else:
            panel_background = INSIGHT_PANEL_LIGHT_BACKGROUND
            panel_border = INSIGHT_PANEL_LIGHT_BORDER
            empty_color = INSIGHT_PANEL_LIGHT_EMPTY_TEXT

        self.setStyleSheet(
            f"""
            ScrollArea#insightStreamPanel {{
                background: {panel_background};
                border: 1px solid {panel_border};
                border-radius: 6px;
            }}
            """
        )
        self.viewport().setStyleSheet(f"background: {panel_background}; border: none;")
        self.container.setStyleSheet(f"background: {panel_background};")
        self.empty_label.setStyleSheet(f"color: {empty_color};")
