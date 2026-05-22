from __future__ import annotations

import json
from typing import Any

from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import PlainTextEdit


class HumanJsonView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.editor = PlainTextEdit(self)
        self.editor.setReadOnly(True)
        root.addWidget(self.editor, 1)

    def set_sections(self, sections: list[dict[str, Any]]) -> None:
        lines: list[str] = []
        for section in sections:
            title = str(section.get("title", "Section"))
            lines.append(title)
            lines.append("=" * len(title))
            lines.append(json.dumps(section.get("items", {}), ensure_ascii=False, indent=2))
            lines.append("")
        self.editor.setPlainText("\n".join(lines).strip())
