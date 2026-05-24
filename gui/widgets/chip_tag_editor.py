from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLayout, QLayoutItem, QSizePolicy, QWidget
from qfluentwidgets import FluentIcon as FIF, LineEdit, PushButton, TransparentToolButton, isDarkTheme

from res.colors import (
    CHARACTER_CARD_ACCENT,
    CHARACTER_CARD_ACCENT_SOFT,
    CHARACTER_CARD_DARK_BORDER,
    CHARACTER_CARD_DARK_MUTED_TEXT,
    CHARACTER_CARD_DARK_PANEL_ALT,
    CHARACTER_CARD_DARK_TEXT,
    CHARACTER_CARD_LIGHT_BORDER,
    CHARACTER_CARD_LIGHT_MUTED_TEXT,
    CHARACTER_CARD_LIGHT_PANEL_ALT,
    CHARACTER_CARD_LIGHT_TEXT,
)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, margin: int = 0, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            item_size = item.sizeHint()
            next_x = x + item_size.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + spacing
                next_x = x + item_size.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            line_height = max(line_height, item_size.height())
        return y + line_height - rect.y() + margins.bottom()


class ChipWidget(QWidget):
    removeRequested = pyqtSignal(str)
    editRequested = pyqtSignal(str)

    def __init__(self, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.value = value
        self.setToolTip(value)
        self.setObjectName("tagChip")
        self.setFixedHeight(25)
        self._apply_colors()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 4, 1)
        layout.setSpacing(4)

        label = QLabel(_elide_middle(value, 26), self)
        label.setToolTip(value)
        label.setMinimumHeight(18)
        label.setMaximumWidth(168)
        layout.addWidget(label)

        remove_button = TransparentToolButton(FIF.CLOSE, self)
        remove_button.setFixedSize(17, 17)
        remove_button.clicked.connect(lambda: self.removeRequested.emit(self.value))
        layout.addWidget(remove_button)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001, N802
        self.editRequested.emit(self.value)
        event.accept()

    def _apply_colors(self) -> None:
        if isDarkTheme():
            text = CHARACTER_CARD_DARK_TEXT
            border = CHARACTER_CARD_DARK_BORDER
            background = "rgba(255, 255, 255, 0.06)"
        else:
            text = CHARACTER_CARD_LIGHT_TEXT
            border = CHARACTER_CARD_LIGHT_BORDER
            background = "rgba(0, 0, 0, 0.04)"
        self.setStyleSheet(
            f"""
            QWidget#tagChip {{
                color: {text};
                background: {background};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            """
        )


class ChipTagEditor(QWidget):
    valuesChanged = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        placeholder: str = "",
        add_text: str = "+ Add",
    ) -> None:
        super().__init__(parent)
        self._values: list[str] = []
        self._updating = False
        self._add_text = add_text
        self._input_active = False

        self.setObjectName("chipTagEditor")

        self.chip_container = QWidget(self)
        self.chip_container.setObjectName("chipTagEditorPanel")
        self.chip_container.setMinimumHeight(27)
        self.chip_container.setMaximumHeight(58)
        self.chip_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.flow = FlowLayout(self.chip_container, spacing=6)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.chip_container.setLayout(self.flow)

        self.input = LineEdit(self)
        self.input.setPlaceholderText(placeholder)
        input_width = max(176, min(280, self.fontMetrics().horizontalAdvance(placeholder) + 34))
        self.input.setFixedWidth(input_width)
        self.input.setFixedHeight(25)
        self.input.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.input.installEventFilter(self)
        self.add_button = PushButton(add_text, self)
        self.add_button.setToolTip(add_text)
        self.add_button.setFixedSize(
            max(70, min(126, self.fontMetrics().horizontalAdvance(add_text) + 18)),
            25,
        )
        self.add_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.chip_container, 1)

        self.input.returnPressed.connect(self._add_from_input)
        self.add_button.clicked.connect(self._start_input)
        self._rebuild()
        self.apply_theme_colors()

    def values(self) -> list[str]:
        return list(self._values)

    def set_values(self, values: list[str]) -> None:
        clean = [_normalize(value) for value in values if _normalize(value)]
        self._updating = True
        self._values = clean
        self.input.clear()
        self._input_active = False
        self._rebuild()
        self._refresh_layout()
        self._updating = False

    def clear(self) -> None:
        self.set_values([])
        self.input.clear()
        self._set_input_active(False)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched is self.input:
            if event.type() == QEvent.Type.FocusOut and not self.input.text().strip():
                self._set_input_active(False)
            elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.input.clear()
                self._set_input_active(False)
                return True
        return super().eventFilter(watched, event)

    def _start_input(self) -> None:
        self._set_input_active(True)
        self.input.setFocus()

    def _set_input_active(self, active: bool) -> None:
        self._input_active = active
        self.input.setVisible(active)
        self.add_button.setVisible(not active)
        self._refresh_layout()

    def _add_from_input(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            self._set_input_active(False)
            return
        additions = [_normalize(part) for part in raw.replace("\uff0c", ",").split(",")]
        additions = [part for part in additions if part]
        if not additions:
            return
        self._values.extend(additions)
        self.input.clear()
        self._set_input_active(False)
        self._rebuild()
        self._emit_values_changed()

    def _remove_value(self, value: str) -> None:
        for index, current in enumerate(self._values):
            if current == value:
                self._values.pop(index)
                self._rebuild()
                self._emit_values_changed()
                return

    def _edit_value(self, value: str) -> None:
        self._remove_value(value)
        self._set_input_active(True)
        self.input.setText(value)
        self.input.setFocus()

    def _rebuild(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None and widget not in (self.input, self.add_button):
                widget.deleteLater()
        for value in self._values:
            chip = ChipWidget(value, self.chip_container)
            chip.removeRequested.connect(self._remove_value)
            chip.editRequested.connect(self._edit_value)
            self.flow.addWidget(chip)
        self.flow.addWidget(self.input)
        self.flow.addWidget(self.add_button)
        self._set_input_active(self._input_active)
        self._refresh_layout()

    def _emit_values_changed(self) -> None:
        if not self._updating:
            self.valuesChanged.emit()

    def _refresh_layout(self) -> None:
        self.flow.invalidate()
        self.chip_container.updateGeometry()
        self.chip_container.update()
        self.updateGeometry()
        self.update()

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            text = CHARACTER_CARD_DARK_TEXT
            muted = CHARACTER_CARD_DARK_MUTED_TEXT
            border = CHARACTER_CARD_DARK_BORDER
            background = CHARACTER_CARD_DARK_PANEL_ALT
        else:
            text = CHARACTER_CARD_LIGHT_TEXT
            muted = CHARACTER_CARD_LIGHT_MUTED_TEXT
            border = CHARACTER_CARD_LIGHT_BORDER
            background = CHARACTER_CARD_LIGHT_PANEL_ALT
        self.chip_container.setStyleSheet(
            f"""
            QWidget#chipTagEditorPanel {{
                color: {text};
                background: transparent;
                border: none;
            }}
            """
        )
        self.input.setStyleSheet(
            f"""
            LineEdit {{
                background: {background};
                border: 1px solid {border};
                border-radius: 12px;
                color: {text};
                padding: 0 8px;
            }}
            LineEdit:disabled {{
                color: {muted};
            }}
            """
        )
        self.add_button.setStyleSheet(
            f"""
            PushButton {{
                color: {muted};
                background: transparent;
                border: 1px dashed {border};
                border-radius: 12px;
                padding: 0 8px;
                font-size: 11px;
            }}
            PushButton:hover {{
                background: {CHARACTER_CARD_ACCENT_SOFT};
                border: 1px solid {CHARACTER_CARD_ACCENT};
                color: {CHARACTER_CARD_ACCENT};
            }}
            """
        )


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().split())


def _elide_middle(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    head = max(8, maximum // 2)
    tail = max(8, maximum - head - 3)
    return f"{value[:head]}...{value[-tail:]}"
