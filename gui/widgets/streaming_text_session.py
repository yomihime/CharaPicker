from __future__ import annotations

from PyQt6.QtGui import QTextCursor


class StreamingTextSession:
    """Lightweight streaming renderer for PlainTextEdit-like widgets."""

    def __init__(self, editor: object) -> None:
        self._editor = editor
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, header_text: str = "") -> None:
        self._editor.setPlainText(header_text)
        self._active = True
        self._scroll_to_end()

    def append_delta(self, delta: str) -> None:
        if not self._active or not delta:
            return
        self._editor.moveCursor(QTextCursor.MoveOperation.End)
        self._editor.insertPlainText(delta)
        self._scroll_to_end()

    def finish(self, footer_text: str = "") -> None:
        if self._active and footer_text:
            self._editor.moveCursor(QTextCursor.MoveOperation.End)
            self._editor.insertPlainText(footer_text)
            self._scroll_to_end()
        self._active = False

    def reset(self, text: str = "") -> None:
        self._editor.setPlainText(text)
        self._active = False
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        scrollbar = self._editor.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
