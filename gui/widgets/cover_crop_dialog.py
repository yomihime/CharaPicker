from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, Slider

from gui.widgets.dialog_middleware import FluentDialog
from utils.i18n import t


class CoverCropDialog(FluentDialog):
    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(t("cards.cover.dialog.title"), parent, width=560, height=620)
        self.image_path = image_path
        self.image = QImage(str(image_path))
        self.crop_rect = _center_9_16_crop(self.image)
        self.crop_scale = 1.0
        self._base_crop_rect = QRect(self.crop_rect)
        self._crop_center_x = self.image.width() / 2 if not self.image.isNull() else 0.0
        self._crop_center_y = self.image.height() / 2 if not self.image.isNull() else 0.0

        description = BodyLabel(t("cards.cover.dialog.description"), self.dialog_card)
        description.setWordWrap(True)
        self.content_layout.addWidget(description)

        self.preview_label = _CropPreviewLabel(self.dialog_card)
        self.preview_label.setFixedSize(240, 426)
        self.preview_label.setScaledContents(True)
        self.preview_label.cropDragged.connect(self._drag_crop)
        self._sync_preview()
        self.content_layout.addWidget(self.preview_label)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(BodyLabel(t("cards.cover.dialog.zoom"), self.dialog_card))
        self.zoom_slider = Slider(Qt.Orientation.Horizontal, self.dialog_card)
        self.zoom_slider.setRange(100, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self._set_zoom)
        reset_button = PushButton(t("cards.cover.dialog.reset"), self.dialog_card)
        reset_button.clicked.connect(self._reset_crop)
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(reset_button)
        self.content_layout.addLayout(zoom_row)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = PushButton(t("cards.cover.dialog.cancel"), self.dialog_card)
        confirm_button = PrimaryPushButton(t("cards.cover.dialog.confirm"), self.dialog_card)
        actions.addWidget(cancel_button)
        actions.addWidget(confirm_button)
        self.content_layout.addLayout(actions)

        cancel_button.clicked.connect(self.reject)
        confirm_button.clicked.connect(self.accept)

    def _set_zoom(self, value: int) -> None:
        self.crop_scale = max(1.0, value / 100)
        self._rebuild_crop_rect()

    def _reset_crop(self) -> None:
        self.crop_scale = 1.0
        self._crop_center_x = self.image.width() / 2 if not self.image.isNull() else 0.0
        self._crop_center_y = self.image.height() / 2 if not self.image.isNull() else 0.0
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(100)
        self.zoom_slider.blockSignals(False)
        self._rebuild_crop_rect()

    def _drag_crop(self, delta_x: int, delta_y: int) -> None:
        if self.image.isNull() or self.crop_rect.isNull():
            return
        source_x = -delta_x * self.crop_rect.width() / max(1, self.preview_label.width())
        source_y = -delta_y * self.crop_rect.height() / max(1, self.preview_label.height())
        self._crop_center_x += source_x
        self._crop_center_y += source_y
        self._rebuild_crop_rect()

    def _rebuild_crop_rect(self) -> None:
        if self.image.isNull() or self._base_crop_rect.isNull():
            self.crop_rect = QRect()
            self._sync_preview()
            return
        width = max(1, int(self._base_crop_rect.width() / self.crop_scale))
        height = max(1, int(self._base_crop_rect.height() / self.crop_scale))
        half_width = width / 2
        half_height = height / 2
        self._crop_center_x = min(max(self._crop_center_x, half_width), self.image.width() - half_width)
        self._crop_center_y = min(max(self._crop_center_y, half_height), self.image.height() - half_height)
        x = int(self._crop_center_x - half_width)
        y = int(self._crop_center_y - half_height)
        self.crop_rect = QRect(x, y, width, height)
        self._sync_preview()

    def _sync_preview(self) -> None:
        cropped = self.image.copy(self.crop_rect) if not self.image.isNull() else QImage()
        self.preview_label.setPixmap(QPixmap.fromImage(cropped))


class _CropPreviewLabel(QLabel):
    cropDragged = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_pos: QPoint | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_pos = event.position().toPoint()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_pos is not None:
            current = event.position().toPoint()
            delta = current - self._last_pos
            self._last_pos = current
            self.cropDragged.emit(delta.x(), delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._last_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


def _center_9_16_crop(image: QImage) -> QRect:
    if image.isNull():
        return QRect()
    source_width = image.width()
    source_height = image.height()
    target_ratio = 9 / 16
    width = source_width
    height = int(width / target_ratio)
    if height > source_height:
        height = source_height
        width = int(height * target_ratio)
    x = max(0, (source_width - width) // 2)
    y = max(0, (source_height - height) // 2)
    return QRect(x, y, width, height)
