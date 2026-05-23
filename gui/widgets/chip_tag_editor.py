from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLayout, QLayoutItem, QSizePolicy, QWidget
from qfluentwidgets import FluentIcon as FIF, LineEdit, PushButton, TransparentToolButton, isDarkTheme

from res.colors import (
    CHARACTER_CARD_ACCENT,
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
        self._apply_colors()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 1, 5, 1)
        layout.setSpacing(4)

        label = QLabel(_elide_middle(value, 28), self)
        label.setToolTip(value)
        label.setMinimumHeight(20)
        label.setMaximumWidth(220)
        layout.addWidget(label)

        remove_button = TransparentToolButton(FIF.CLOSE, self)
        remove_button.setFixedSize(20, 20)
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
                border-radius: 6px;
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

        self.setObjectName("chipTagEditor")

        self.chip_container = QWidget(self)
        self.chip_container.setObjectName("chipTagEditorPanel")
        self.chip_container.setMinimumHeight(38)
        self.chip_container.setMaximumHeight(70)
        self.chip_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.flow = FlowLayout(self.chip_container, spacing=6)
        self.flow.setContentsMargins(7, 5, 7, 5)
        self.chip_container.setLayout(self.flow)

        self.input = LineEdit(self)
        self.input.setPlaceholderText(placeholder)
        self.input.setMinimumWidth(120)
        self.input.setMaximumWidth(260)
        self.input.setMinimumHeight(28)
        self.input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.add_button = PushButton("+", self)
        self.add_button.setToolTip(add_text)
        self.add_button.setFixedSize(32, 28)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.chip_container, 1)

        self.input.returnPressed.connect(self._add_from_input)
        self.add_button.clicked.connect(self._add_from_input)
        self._rebuild()
        self.apply_theme_colors()

    def values(self) -> list[str]:
        return list(self._values)

    def set_values(self, values: list[str]) -> None:
        clean = [_normalize(value) for value in values if _normalize(value)]
        self._updating = True
        self._values = clean
        self._rebuild()
        self._updating = False

    def clear(self) -> None:
        self.set_values([])
        self.input.clear()

    def _add_from_input(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            return
        additions = [_normalize(part) for part in raw.replace("\uff0c", ",").split(",")]
        additions = [part for part in additions if part]
        if not additions:
            return
        self._values.extend(additions)
        self.input.clear()
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
        self.updateGeometry()

    def _emit_values_changed(self) -> None:
        if not self._updating:
            self.valuesChanged.emit()

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
                background: {background};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            """
        )
        self.input.setStyleSheet(
            f"""
            LineEdit {{
                background: transparent;
                border: none;
                color: {text};
            }}
            LineEdit:disabled {{
                color: {muted};
            }}
            """
        )
        self.add_button.setStyleSheet(
            f"""
            PushButton {{
                color: {CHARACTER_CARD_ACCENT};
                border-radius: 6px;
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
