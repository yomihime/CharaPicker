from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    LineEdit,
    PushButton,
    StrongBodyLabel,
    TransparentToolButton,
    isDarkTheme,
)

from core.models import CharacterCardStatus, CharacterCardSummary
from gui.widgets.chip_tag_editor import FlowLayout
from res.colors import (
    CHARACTER_CARD_ACCENT,
    CHARACTER_CARD_ACCENT_SOFT,
    CHARACTER_CARD_DARK_BORDER,
    CHARACTER_CARD_DARK_MUTED_TEXT,
    CHARACTER_CARD_DARK_PANEL,
    CHARACTER_CARD_DARK_PANEL_ALT,
    CHARACTER_CARD_DARK_TEXT,
    CHARACTER_CARD_LIGHT_BORDER,
    CHARACTER_CARD_LIGHT_MUTED_TEXT,
    CHARACTER_CARD_LIGHT_PANEL,
    CHARACTER_CARD_LIGHT_PANEL_ALT,
    CHARACTER_CARD_LIGHT_TEXT,
    CHARACTER_CARD_STATUS_COMPILED,
    CHARACTER_CARD_STATUS_DRAFT,
    CHARACTER_CARD_STATUS_FAILED,
    CHARACTER_CARD_STATUS_PREVIEW,
    CHARACTER_CARD_STATUS_STALE,
)
from utils.i18n import t


CARD_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 100


class CharacterCardGallery(QWidget):
    cardSelected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[CharacterCardSummary] = []
        self._status_filter: CharacterCardStatus | None = None
        self.setObjectName("characterCardGalleryPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(0)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(7)

        title = StrongBodyLabel(t("cards.gallery.title"), self)
        root.addWidget(title)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = LineEdit(self)
        self.search_edit.setPlaceholderText(t("cards.search.placeholder"))
        self.filter_button = TransparentToolButton(FIF.FILTER, self)
        self.filter_button.setToolTip(t("cards.gallery.filter.tooltip"))
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.filter_button)
        root.addLayout(search_row)

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[CharacterCardStatus | None, PushButton] = {}
        filter_panel = QWidget(self)
        filter_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        filter_row = FlowLayout(filter_panel, spacing=4)
        filter_panel.setLayout(filter_row)
        for status, label in (
            (None, t("cards.statusFilter.all")),
            (CharacterCardStatus.DRAFT, t("cards.statusFilter.draft")),
            (CharacterCardStatus.COMPILED, t("cards.statusFilter.compiled")),
            (CharacterCardStatus.STALE, t("cards.statusFilter.stale")),
        ):
            button = PushButton(label, self)
            button.setCheckable(True)
            button.setToolTip(label)
            button.setFixedSize(_filter_chip_width(button, label), 26)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=status: self._set_status_filter(value))
            self.filter_group.addButton(button)
            self.filter_buttons[status] = button
            filter_row.addWidget(button)
        root.addWidget(filter_panel)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("characterCardGallery")
        self.list_widget.setMinimumWidth(0)
        self.list_widget.setSpacing(5)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        root.addWidget(self.list_widget, 1)

        self.empty_label = CaptionLabel(t("cards.empty.noCards"), self)
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        self.count_label = CaptionLabel("", self)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.count_label)

        self.search_edit.textChanged.connect(self._refresh_items)
        self.list_widget.currentItemChanged.connect(self._emit_selected)
        self._sync_filter_buttons()
        self.apply_theme_colors()

    def set_cards(self, cards: list[CharacterCardSummary]) -> None:
        self._cards = list(cards)
        self._refresh_items()

    def selected_card_id(self) -> str:
        item = self.list_widget.currentItem()
        return str(item.data(CARD_ID_ROLE)) if item is not None else ""

    def select_card(self, card_id: str) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(CARD_ID_ROLE) == card_id:
                self.list_widget.setCurrentRow(row)
                self._sync_selection_styles()
                return

    def apply_theme_colors(self) -> None:
        if isDarkTheme():
            panel = CHARACTER_CARD_DARK_PANEL
            background = CHARACTER_CARD_DARK_PANEL_ALT
            border = CHARACTER_CARD_DARK_BORDER
            text = CHARACTER_CARD_DARK_TEXT
            muted = CHARACTER_CARD_DARK_MUTED_TEXT
        else:
            panel = CHARACTER_CARD_LIGHT_PANEL
            background = CHARACTER_CARD_LIGHT_PANEL_ALT
            border = CHARACTER_CARD_LIGHT_BORDER
            text = CHARACTER_CARD_LIGHT_TEXT
            muted = CHARACTER_CARD_LIGHT_MUTED_TEXT
        self.list_widget.setStyleSheet(
            f"""
            QListWidget#characterCardGallery {{
                background: {background};
                border: 1px solid {border};
                border-radius: 8px;
                outline: none;
                padding: 5px;
            }}
            QListWidget#characterCardGallery::item {{
                border: none;
                padding: 0;
                margin: 0;
            }}
            QListWidget#characterCardGallery::item:selected {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
                margin: 2px 0 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(169, 176, 184, 0.22);
                border-radius: 3px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(169, 176, 184, 0.36);
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                height: 0;
                background: transparent;
            }}
            """
        )
        self.empty_label.setStyleSheet(f"color: {muted};")
        self.count_label.setStyleSheet(f"color: {muted};")
        self.setStyleSheet(
            f"""
            QWidget#characterCardGalleryPanel {{
                color: {text};
                background: {panel};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QWidget#characterCardGalleryPanel QWidget {{
                color: {text};
            }}
            """
        )
        self._sync_filter_buttons()
        self._sync_selection_styles()

    def _set_status_filter(self, status: CharacterCardStatus | None) -> None:
        self._status_filter = status
        self._sync_filter_buttons()
        self._refresh_items()

    def _refresh_items(self) -> None:
        selected_id = self.selected_card_id()
        query = self.search_edit.text().strip().casefold()
        self.list_widget.clear()
        visible_cards = [card for card in self._cards if self._matches(card, query)]
        for card in visible_cards:
            item = QListWidgetItem()
            item.setData(CARD_ID_ROLE, card.card_id)
            item.setToolTip(card.card_id)
            item.setSizeHint(QSize(0, 86))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, PosterCardWidget(card, self.list_widget))
        self.empty_label.setVisible(self.list_widget.count() == 0)
        self.count_label.setText(t("cards.gallery.count", count=len(self._cards)))
        if selected_id:
            self.select_card(selected_id)
        self._sync_selection_styles()

    def _matches(self, card: CharacterCardSummary, query: str) -> bool:
        if self._status_filter is not None:
            if self._status_filter == CharacterCardStatus.DRAFT:
                if card.compile_status not in (CharacterCardStatus.DRAFT, CharacterCardStatus.EMPTY):
                    return False
            elif card.compile_status != self._status_filter:
                return False
        haystack = " ".join(
            [
                card.display_name,
                card.character_name,
                " ".join(card.aliases),
                " ".join(card.tags),
                card.notes,
                card.compile_status.value,
                card.compile_source.value,
                card.compile_variant.value,
            ]
        ).casefold()
        return not query or query in haystack

    def _emit_selected(self, current: QListWidgetItem | None) -> None:
        self._sync_selection_styles()
        if current is not None:
            self.cardSelected.emit(str(current.data(CARD_ID_ROLE)))

    def _sync_selection_styles(self) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, PosterCardWidget):
                widget.set_selected(item is self.list_widget.currentItem())

    def _sync_filter_buttons(self) -> None:
        if isDarkTheme():
            inactive_text = CHARACTER_CARD_DARK_TEXT
            inactive_border = CHARACTER_CARD_DARK_BORDER
            inactive_background = "rgba(255, 255, 255, 0.035)"
        else:
            inactive_text = CHARACTER_CARD_LIGHT_TEXT
            inactive_border = CHARACTER_CARD_LIGHT_BORDER
            inactive_background = "rgba(0, 0, 0, 0.035)"
        for status, button in self.filter_buttons.items():
            checked = status == self._status_filter
            button.setChecked(checked)
            if checked:
                button.setStyleSheet(
                    f"""
                    PushButton {{
                        color: {CHARACTER_CARD_ACCENT};
                        border: 1px solid {CHARACTER_CARD_ACCENT};
                        background: {CHARACTER_CARD_ACCENT_SOFT};
                        border-radius: 13px;
                        padding: 0 7px;
                        font-size: 11px;
                    }}
                    """
                )
            else:
                button.setStyleSheet(
                    f"""
                    PushButton {{
                        color: {inactive_text};
                        border: 1px solid {inactive_border};
                        background: {inactive_background};
                        border-radius: 13px;
                        padding: 0 7px;
                        font-size: 11px;
                    }}
                    PushButton:hover {{
                        border: 1px solid {CHARACTER_CARD_ACCENT};
                        background: {CHARACTER_CARD_ACCENT_SOFT};
                    }}
                    """
                )


class PosterCardWidget(QWidget):
    def __init__(self, card: CharacterCardSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.card = card
        self._selected = False
        self.setObjectName("posterCard")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 6, 7, 6)
        root.setSpacing(7)

        self.selection_bar = QWidget(self)
        self.selection_bar.setObjectName("selectionBar")
        self.selection_bar.setFixedWidth(3)
        root.addWidget(self.selection_bar)

        self.cover = CoverThumbnail(self)
        self.cover.set_cover_path(card.cover_path)
        root.addWidget(self.cover, 0)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(2)
        name = _display_name_with_tags(card)
        self.name_label = BodyLabel(_elide_text(name, 44), self)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(34)
        self.name_label.setToolTip(name)
        content.addWidget(self.name_label)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        self.status_badge = QLabel(_status_text(card.compile_status), self)
        self.status_badge.setObjectName("statusBadge")
        status_row.addWidget(self.status_badge, 0)
        status_row.addStretch(1)
        content.addLayout(status_row)

        self.source_label = CaptionLabel(_secondary_text(card), self)
        self.source_label.setWordWrap(False)
        content.addWidget(self.source_label)

        self.meta_label = CaptionLabel(
            t(
                "cards.gallery.itemMeta",
                revision=card.revision,
                format=_variant_text(card.compile_variant.value),
            ),
            self,
        )
        content.addWidget(self.meta_label)
        content.addStretch(1)
        root.addLayout(content, 1)

        self._apply_styles()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_styles()

    def _apply_styles(self) -> None:
        if isDarkTheme():
            panel = CHARACTER_CARD_DARK_PANEL
            border = CHARACTER_CARD_DARK_BORDER
            text = CHARACTER_CARD_DARK_TEXT
            muted = CHARACTER_CARD_DARK_MUTED_TEXT
        else:
            panel = CHARACTER_CARD_LIGHT_PANEL
            border = CHARACTER_CARD_LIGHT_BORDER
            text = CHARACTER_CARD_LIGHT_TEXT
            muted = CHARACTER_CARD_LIGHT_MUTED_TEXT
        selected_border = CHARACTER_CARD_ACCENT if self._selected else border
        selected_background = "rgba(37, 217, 232, 0.10)" if self._selected else panel
        self.setStyleSheet(
            f"""
            QWidget#posterCard {{
                background: {selected_background};
                border: 1px solid {selected_border};
                border-radius: 8px;
            }}
            QWidget#selectionBar {{
                background: {CHARACTER_CARD_ACCENT if self._selected else "transparent"};
                border-radius: 2px;
            }}
            QLabel#statusBadge {{
                color: {_status_foreground(self.card.compile_status)};
                background: {_status_background(self.card.compile_status)};
                border-radius: 7px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            """
        )
        self.name_label.setStyleSheet(f"color: {text}; font-weight: 600;")
        self.source_label.setStyleSheet(f"color: {muted};")
        self.meta_label.setStyleSheet(f"color: {muted};")


class CoverThumbnail(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(38, 68)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)

    def set_cover_path(self, cover_path: str) -> None:
        pixmap = QPixmap()
        if cover_path and Path(cover_path).exists():
            pixmap = QPixmap(cover_path)
        if pixmap.isNull():
            self.clear()
            self.setText("9:16")
            self.setStyleSheet(
                f"""
                QLabel {{
                    color: {CHARACTER_CARD_DARK_MUTED_TEXT};
                    border: 1px dashed {CHARACTER_CARD_DARK_BORDER};
                    border-radius: 6px;
                    background: rgba(255, 255, 255, 0.04);
                }}
                """
            )
            return
        self.setText("")
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setStyleSheet("QLabel { border-radius: 6px; background: transparent; }")


def _display_name_with_tags(card: CharacterCardSummary) -> str:
    name = card.display_name or card.character_name or card.card_id
    tags = f" [{', '.join(card.tags)}]" if card.tags else ""
    return f"{name}{tags}"


def _secondary_text(card: CharacterCardSummary) -> str:
    return card.compile_source.value


def _status_text(status: CharacterCardStatus) -> str:
    if status == CharacterCardStatus.STALE:
        return t("cards.statusFilter.stale")
    return status.value


def _status_foreground(status: CharacterCardStatus) -> str:
    if status == CharacterCardStatus.STALE:
        return "#f8e08e"
    if status == CharacterCardStatus.FAILED:
        return "#ffd8d8"
    if status == CharacterCardStatus.COMPILED:
        return "#c9fbff"
    if status == CharacterCardStatus.PREVIEW:
        return "#eee5ff"
    return "#eef1f4"


def _status_background(status: CharacterCardStatus) -> str:
    color = {
        CharacterCardStatus.COMPILED: CHARACTER_CARD_STATUS_COMPILED,
        CharacterCardStatus.STALE: CHARACTER_CARD_STATUS_STALE,
        CharacterCardStatus.FAILED: CHARACTER_CARD_STATUS_FAILED,
        CharacterCardStatus.PREVIEW: CHARACTER_CARD_STATUS_PREVIEW,
    }.get(status, CHARACTER_CARD_STATUS_DRAFT)
    return f"{color}66"


def _variant_text(value: str) -> str:
    return t(f"cards.compileVariant.{value}")


def _filter_chip_width(button: PushButton, label: str) -> int:
    return max(36, min(68, button.fontMetrics().horizontalAdvance(label) + 14))


def _elide_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: max(0, maximum - 3)].rstrip() + "..."
