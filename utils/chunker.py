from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class TextChunkingResult:
    chunks: list[TextChunk]
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False


def chunk_text(text: str, size: int = 1800) -> list[str]:
    if size <= 0:
        raise ValueError("size must be greater than 0")
    return [text[index : index + size] for index in range(0, len(text), size)]


def chunk_text_with_ranges(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int = 0,
    max_chunks: int | None = None,
) -> TextChunkingResult:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than 0")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must not be negative")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")
    if max_chunks is not None and max_chunks <= 0:
        raise ValueError("max_chunks must be greater than 0")

    chunks: list[TextChunk] = []
    warnings: list[str] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        if max_chunks is not None and len(chunks) >= max_chunks:
            warnings.append(
                f"text_chunk_limit_reached:max_chunks={max_chunks}:remaining_chars={text_length - start}"
            )
            return TextChunkingResult(chunks=chunks, warnings=warnings, truncated=True)

        hard_end = min(text_length, start + max_chars)
        end = _preferred_text_boundary(text, start, hard_end) if hard_end < text_length else hard_end
        if end <= start:
            end = hard_end
        chunk_value = text[start:end]
        if chunk_value.strip():
            chunks.append(
                TextChunk(
                    index=len(chunks) + 1,
                    text=chunk_value,
                    start_offset=start,
                    end_offset=end,
                )
            )
        if end >= text_length:
            break
        start = max(start + 1, end - overlap_chars)

    if len(chunks) > 1:
        warnings.append(f"text_split_into_chunks:count={len(chunks)}")
    return TextChunkingResult(chunks=chunks, warnings=warnings)


def _preferred_text_boundary(text: str, start: int, hard_end: int) -> int:
    minimum = start + max(1, int((hard_end - start) * 0.6))
    for marker in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", " "):
        position = text.rfind(marker, minimum, hard_end)
        if position >= minimum:
            return position + len(marker)
    return hard_end
