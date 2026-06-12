from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from utils.media_types import SUPPORTED_TIMED_TEXT_SUFFIXES


_SRT_TIME_PATTERN = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?$"
)
_ASS_OVERRIDE_PATTERN = re.compile(r"\{[^{}]*\}")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class TimedTextSegment:
    index: int
    source_line: int
    start_seconds: float
    end_seconds: float
    text: str
    raw_text: str
    speaker: str = ""
    start_offset: int = 0
    end_offset: int = 0


@dataclass(frozen=True, slots=True)
class TimedTextDocument:
    text: str
    segments: list[TimedTextSegment]
    format_name: str
    warnings: list[str] = field(default_factory=list)


def parse_timed_text(path: Path, text: str) -> TimedTextDocument:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TIMED_TEXT_SUFFIXES:
        raise ValueError(f"unsupported timed text suffix: {suffix or '<none>'}")
    if suffix == ".srt":
        segments, warnings = _parse_srt(text)
        return _build_document(segments, format_name="srt", warnings=warnings)
    segments, warnings = _parse_ass(text)
    return _build_document(segments, format_name="ass", warnings=warnings)


def _parse_srt(text: str) -> tuple[list[TimedTextSegment], list[str]]:
    lines = text.splitlines()
    segments: list[TimedTextSegment] = []
    warnings: list[str] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        cue_line = index
        cue_id = lines[index].strip()
        if cue_id.isdigit() and index + 1 < len(lines):
            index += 1
        timing_match = _SRT_TIME_PATTERN.match(lines[index]) if index < len(lines) else None
        if timing_match is None:
            warnings.append(f"srt_cue_skipped:line={cue_line + 1}")
            while index < len(lines) and lines[index].strip():
                index += 1
            continue

        timing_line = index + 1
        start_seconds = _parse_clock(timing_match.group("start"), fraction_scale=1_000)
        end_seconds = _parse_clock(timing_match.group("end"), fraction_scale=1_000)
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index])
            index += 1
        raw_text = "\n".join(text_lines).strip()
        normalized = _clean_srt_text(raw_text)
        if not normalized:
            warnings.append(f"srt_empty_cue_skipped:line={timing_line}")
            continue
        segments.append(
            TimedTextSegment(
                index=len(segments) + 1,
                source_line=timing_line,
                start_seconds=start_seconds,
                end_seconds=max(start_seconds, end_seconds),
                text=normalized,
                raw_text=raw_text,
            )
        )
    return segments, warnings


def _parse_ass(text: str) -> tuple[list[TimedTextSegment], list[str]]:
    lines = text.splitlines()
    in_events = False
    fields: list[str] = []
    segments: list[TimedTextSegment] = []
    warnings: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_events = stripped.lower() == "[events]"
            continue
        if not in_events or not stripped:
            continue
        key, separator, value = stripped.partition(":")
        normalized_key = key.strip().lower()
        if normalized_key == "format" and separator:
            fields = [item.strip().lower() for item in value.split(",")]
            continue
        if normalized_key != "dialogue" or not separator:
            continue
        if not fields:
            warnings.append(f"ass_dialogue_skipped_without_format:line={line_number}")
            continue
        values = value.lstrip().split(",", max(len(fields) - 1, 0))
        if len(values) != len(fields):
            warnings.append(f"ass_dialogue_field_mismatch:line={line_number}")
            continue
        record = dict(zip(fields, values))
        try:
            start_seconds = _parse_clock(record.get("start", ""), fraction_scale=100)
            end_seconds = _parse_clock(record.get("end", ""), fraction_scale=100)
        except ValueError:
            warnings.append(f"ass_dialogue_time_invalid:line={line_number}")
            continue
        raw_text = record.get("text", "").strip()
        normalized = _clean_ass_text(raw_text)
        if not normalized:
            warnings.append(f"ass_empty_dialogue_skipped:line={line_number}")
            continue
        segments.append(
            TimedTextSegment(
                index=len(segments) + 1,
                source_line=line_number,
                start_seconds=start_seconds,
                end_seconds=max(start_seconds, end_seconds),
                text=normalized,
                raw_text=raw_text,
                speaker=record.get("name", "").strip(),
            )
        )
    return segments, warnings


def _build_document(
    segments: list[TimedTextSegment],
    *,
    format_name: str,
    warnings: list[str],
) -> TimedTextDocument:
    rendered_parts: list[str] = []
    positioned_segments: list[TimedTextSegment] = []
    offset = 0
    for segment in segments:
        speaker = segment.speaker or "unknown"
        rendered = (
            f"[cue={segment.index} line={segment.source_line} "
            f"time={_format_seconds(segment.start_seconds)}-{_format_seconds(segment.end_seconds)} "
            f"speaker={speaker}]\n{segment.text}"
        )
        if rendered_parts:
            rendered = "\n" + rendered
        start_offset = offset + (1 if rendered_parts else 0)
        rendered_parts.append(rendered)
        offset += len(rendered)
        positioned_segments.append(
            replace(
                segment,
                start_offset=start_offset,
                end_offset=offset,
            )
        )
    if not positioned_segments:
        warnings.append(f"{format_name}_no_usable_segments")
    return TimedTextDocument(
        text="".join(rendered_parts),
        segments=positioned_segments,
        format_name=format_name,
        warnings=warnings,
    )


def _parse_clock(value: str, *, fraction_scale: int) -> float:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) != 3:
        raise ValueError(f"invalid timed text clock: {value}")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds_text, separator, fraction_text = parts[2].partition(".")
    seconds = int(seconds_text)
    fraction = int((fraction_text or "0")[:3]) / fraction_scale if separator else 0.0
    return hours * 3_600 + minutes * 60 + seconds + fraction


def _clean_srt_text(value: str) -> str:
    unescaped = html.unescape(value)
    return _HTML_TAG_PATTERN.sub("", unescaped).strip()


def _clean_ass_text(value: str) -> str:
    without_overrides = _ASS_OVERRIDE_PATTERN.sub("", value)
    return without_overrides.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ").strip()


def _format_seconds(value: float) -> str:
    milliseconds = max(0, round(value * 1_000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
