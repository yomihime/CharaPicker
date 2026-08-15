from __future__ import annotations

from collections.abc import Callable


class ProgressGuard:
    """Keep worker progress monotonic and reserve 100 for confirmed success."""

    def __init__(self, emit: Callable[[int], None]) -> None:
        self._emit = emit
        self._value = 0
        self._terminal = False

    @property
    def value(self) -> int:
        return self._value

    @property
    def terminal(self) -> bool:
        return self._terminal

    def update(self, value: int) -> None:
        if self._terminal:
            return
        normalized = max(0, min(99, int(value)))
        if normalized <= self._value:
            return
        self._value = normalized
        self._emit(normalized)

    def succeed(self) -> None:
        if self._terminal:
            return
        self._terminal = True
        self._value = 100
        self._emit(100)

    def fail(self) -> None:
        self._terminal = True
