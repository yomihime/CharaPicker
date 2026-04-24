from __future__ import annotations


def chunk_text(text: str, size: int = 1800) -> list[str]:
    if size <= 0:
        raise ValueError("size must be greater than 0")
    return [text[index : index + size] for index in range(0, len(text), size)]
