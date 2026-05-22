from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, LineEdit

from core.models import CharacterCardSummary
from utils.i18n import t


CARD_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 100


class CharacterCardGallery(QWidget):
    cardSelected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[CharacterCardSummary] = []
        self.setMinimumWidth(300)
        self.setMaximumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(BodyLabel(t("cards.gallery.title"), self))
        self.search_edit = LineEdit(self)
        self.search_edit.setPlaceholderText(t("cards.search.placeholder"))
        root.addWidget(self.search_edit)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("characterCardGallery")
        self.list_widget.setMinimumWidth(300)
        self.list_widget.setIconSize(QSize(54, 96))
        root.addWidget(self.list_widget, 1)

        self.empty_label = CaptionLabel(t("cards.empty.noCards"), self)
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        self.search_edit.textChanged.connect(self._refresh_items)
        self.list_widget.currentItemChanged.connect(self._emit_selected)

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
                return

    def _refresh_items(self) -> None:
        query = self.search_edit.text().strip().casefold()
        self.list_widget.clear()
        for card in self._cards:
            haystack = " ".join(
                [
                    card.display_name,
                    card.character_name,
                    " ".join(card.aliases),
                    " ".join(card.tags),
                    card.notes,
                    card.compile_status.value,
                ]
            ).casefold()
            if query and query not in haystack:
                continue
            item = QListWidgetItem(self._item_text(card))
            item.setData(CARD_ID_ROLE, card.card_id)
            item.setToolTip(card.card_id)
            if card.cover_path:
                icon = QIcon(card.cover_path)
                if not icon.isNull():
                    item.setIcon(icon)
            self.list_widget.addItem(item)
        self.empty_label.setVisible(self.list_widget.count() == 0)

    def _emit_selected(self, current: QListWidgetItem | None) -> None:
        if current is not None:
            self.cardSelected.emit(str(current.data(CARD_ID_ROLE)))

    def _item_text(self, card: CharacterCardSummary) -> str:
        name = card.display_name or card.character_name or card.card_id
        tags = f" [{', '.join(card.tags)}]" if card.tags else ""
        return f"{name}{tags}\n{card.compile_status.value}"
