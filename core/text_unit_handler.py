from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.extraction_ai import (
    FormalExtractionJsonResult,
    build_formal_text_json_request,
    call_formal_text_json_model,
)
from core.extraction_plan import (
    EvidenceRef,
    ExtractionUnit,
    MediaType,
    SourceTrace,
    TextRange,
    TimeRange,
)
from core.models import ChunkExtractionResult, EpisodeTranscript, ExtractionArtifactStage
from core.timed_text_parser import (
    TimedTextSegment,
    build_timed_text_document,
    parse_timed_text,
)
from utils.ai_model_middleware import ModelBackend, ModelCallRequest
from utils.chunker import TextChunkingResult, chunk_text_with_ranges
from utils.media_types import SUPPORTED_TIMED_TEXT_SUFFIXES


TEXT_DOCUMENT_UNIT_KINDS = frozenset({"document_text", "controlled_json_text"})
TIMED_TEXT_UNIT_KINDS = frozenset({"subtitle_text"})
TRANSCRIPT_TEXT_UNIT_KINDS = frozenset({"transcript_text"})
TEXT_DOCUMENT_SUFFIXES = frozenset({".txt", ".md", ".json"})
TEXT_DECODE_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "shift_jis")
ModelJsonCall = Callable[[ModelCallRequest], FormalExtractionJsonResult]


@dataclass(frozen=True, slots=True)
class TextUnitHandlerConfig:
    max_input_chars: int = 12_000
    overlap_chars: int = 400
    max_chunks_per_unit: int = 128
    max_output_tokens: int = 2_048


@dataclass(frozen=True, slots=True)
class ParsedTextMaterial:
    text: str
    encoding: str
    warnings: list[str] = field(default_factory=list)
    timed_text_format: str = ""
    timed_segments: list[TimedTextSegment] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PreparedTextChunk:
    index: int
    text: str
    start_offset: int
    end_offset: int
    timed_text_format: str = ""
    timed_segments: list[TimedTextSegment] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TextUnitExecutionResult:
    chunks: list[ChunkExtractionResult]
    warnings: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)


class TextUnitHandler:
    def __init__(
        self,
        config: TextUnitHandlerConfig | None = None,
        *,
        model_call: ModelJsonCall = call_formal_text_json_model,
    ) -> None:
        self.config = config or TextUnitHandlerConfig()
        self._model_call = model_call

    def supports(self, unit: ExtractionUnit) -> bool:
        if unit.media_type != MediaType.TEXT:
            return False
        if unit.unit_kind in TEXT_DOCUMENT_UNIT_KINDS:
            return True
        if unit.unit_kind in TRANSCRIPT_TEXT_UNIT_KINDS:
            return True
        return (
            unit.unit_kind in TIMED_TEXT_UNIT_KINDS
            and Path(unit.material_ref.relative_path).suffix.lower()
            in SUPPORTED_TIMED_TEXT_SUFFIXES
        )

    def execute(
        self,
        *,
        source_root: Path,
        unit: ExtractionUnit,
        season_id: str,
        extraction_stage: ExtractionArtifactStage,
        extraction_run_id: str,
        run_type: str,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        chunk_limit: int | None = None,
    ) -> TextUnitExecutionResult:
        if not self.supports(unit):
            raise ValueError(f"unsupported text extraction unit: {unit.unit_kind}")

        source_path = self._source_path(source_root, unit)
        parsed = self.parse_material(source_path, unit_kind=unit.unit_kind)
        prepared_chunks, chunk_warnings = self._prepare_chunks(parsed, chunk_limit=chunk_limit)
        warnings = [*parsed.warnings, *chunk_warnings]
        output: list[ChunkExtractionResult] = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for text_chunk in prepared_chunks:
            chunk_id = f"{unit.unit_id}_text_{text_chunk.index:04d}"
            source_locator = self._source_locator(text_chunk)
            evidence_guidance = self._evidence_guidance(text_chunk)
            request = build_formal_text_json_request(
                purpose=(
                    "preview_text_unit_extraction"
                    if extraction_stage == ExtractionArtifactStage.PREVIEW
                    else "formal_text_unit_extraction"
                ),
                backend=backend,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                variables={
                    "season_id": season_id,
                    "episode_id": unit.episode_id,
                    "chunk_id": chunk_id,
                    "source_path": unit.material_ref.relative_path,
                    "content_form": unit.content_form.value,
                    "source_locator": source_locator,
                    "text_range": source_locator,
                    "evidence_guidance": evidence_guidance,
                    "chunk_text": text_chunk.text,
                },
                max_tokens=self.config.max_output_tokens,
                metadata={
                    "stage": extraction_stage.value,
                    "season_id": season_id,
                    "episode_id": unit.episode_id,
                    "chunk_id": chunk_id,
                    "source_path": unit.material_ref.relative_path,
                    "media_type": MediaType.TEXT.value,
                    "content_form": unit.content_form.value,
                    "unit_kind": unit.unit_kind,
                    "timed_text_format": parsed.timed_text_format,
                },
            )
            result = self._model_call(request)
            for key in usage_total:
                value = result.token_usage.get(key)
                if isinstance(value, int):
                    usage_total[key] += value
            output.append(
                self._chunk_result(
                    unit=unit,
                    season_id=season_id,
                    chunk_id=chunk_id,
                    text_range=TextRange(
                        start_offset=text_chunk.start_offset,
                        end_offset=text_chunk.end_offset,
                        chapter=(unit.material_ref.text_range.chapter if unit.material_ref.text_range else ""),
                        section=f"chunk_{text_chunk.index:04d}",
                    ),
                    timed_segments=text_chunk.timed_segments,
                    extraction_stage=extraction_stage,
                    extraction_run_id=extraction_run_id,
                    run_type=run_type,
                    payload=result.payload,
                    result=result,
                    warnings=warnings if text_chunk.index == 1 else [],
                )
            )
        return TextUnitExecutionResult(
            chunks=output,
            warnings=warnings,
            token_usage=usage_total,
        )

    def parse_material(self, path: Path, *, unit_kind: str = "") -> ParsedTextMaterial:
        suffix = path.suffix.lower()
        if suffix not in TEXT_DOCUMENT_SUFFIXES | SUPPORTED_TIMED_TEXT_SUFFIXES:
            raise ValueError(f"unsupported text material suffix: {suffix or '<none>'}")
        raw = path.read_bytes()
        text, encoding = self._decode_text(raw, path)
        warnings: list[str] = []
        if encoding not in {"utf-8", "utf-8-sig"}:
            warnings.append(f"text_decoded_with_fallback:{encoding}")
        if unit_kind in TRANSCRIPT_TEXT_UNIT_KINDS:
            return self._parse_transcript_material(text, encoding=encoding, warnings=warnings)
        if suffix in SUPPORTED_TIMED_TEXT_SUFFIXES:
            document = parse_timed_text(path, text)
            return ParsedTextMaterial(
                text=document.text,
                encoding=encoding,
                warnings=[*warnings, *document.warnings],
                timed_text_format=document.format_name,
                timed_segments=document.segments,
            )
        if suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"controlled JSON text is invalid: {path.name}") from exc
            if not isinstance(payload, (dict, list)):
                raise ValueError("controlled JSON text must contain an object or array")
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        return ParsedTextMaterial(text=text, encoding=encoding, warnings=warnings)

    def _parse_transcript_material(
        self,
        text: str,
        *,
        encoding: str,
        warnings: list[str],
    ) -> ParsedTextMaterial:
        try:
            transcript = EpisodeTranscript.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("transcript material is not a valid EpisodeTranscript") from exc
        segments = [
            TimedTextSegment(
                index=index,
                source_line=None,
                start_seconds=segment.start_seconds,
                end_seconds=max(segment.start_seconds, segment.end_seconds),
                text=segment.text.strip(),
                raw_text=segment.text,
            )
            for index, segment in enumerate(transcript.segments, start=1)
            if segment.text.strip()
        ]
        if not segments and transcript.plain_text.strip():
            segments.append(
                TimedTextSegment(
                    index=1,
                    source_line=None,
                    start_seconds=0.0,
                    end_seconds=0.0,
                    text=transcript.plain_text.strip(),
                    raw_text=transcript.plain_text,
                )
            )
        document = build_timed_text_document(
            segments,
            format_name="transcript",
            warnings=warnings,
        )
        return ParsedTextMaterial(
            text=document.text,
            encoding=encoding,
            warnings=document.warnings,
            timed_text_format=document.format_name,
            timed_segments=document.segments,
        )

    def _prepare_chunks(
        self,
        parsed: ParsedTextMaterial,
        *,
        chunk_limit: int | None,
    ) -> tuple[list[PreparedTextChunk], list[str]]:
        if parsed.timed_segments:
            return self._chunk_timed_segments(parsed, chunk_limit=chunk_limit)
        chunking = self.chunk_material(parsed.text, chunk_limit=chunk_limit)
        return (
            [
                PreparedTextChunk(
                    index=chunk.index,
                    text=chunk.text,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                )
                for chunk in chunking.chunks
            ],
            chunking.warnings,
        )

    def _chunk_timed_segments(
        self,
        parsed: ParsedTextMaterial,
        *,
        chunk_limit: int | None,
    ) -> tuple[list[PreparedTextChunk], list[str]]:
        max_chunks = self.config.max_chunks_per_unit
        if chunk_limit is not None:
            max_chunks = min(max_chunks, max(1, chunk_limit))
        chunks: list[PreparedTextChunk] = []
        warnings: list[str] = []
        current: list[TimedTextSegment] = []
        for segment in parsed.timed_segments:
            candidate = [*current, segment]
            candidate_text = self._timed_chunk_text(parsed.text, candidate)
            if current and len(candidate_text) > self.config.max_input_chars:
                chunks.append(
                    self._prepared_timed_chunk(
                        parsed.text,
                        current,
                        len(chunks) + 1,
                        parsed.timed_text_format,
                    )
                )
                if len(chunks) >= max_chunks:
                    remaining = len(parsed.timed_segments) - sum(
                        len(chunk.timed_segments) for chunk in chunks
                    )
                    warnings.append(
                        f"timed_text_chunk_limit_reached:max_chunks={max_chunks}:"
                        f"remaining_segments={max(remaining, 0)}"
                    )
                    return chunks, warnings
                current = [segment]
            else:
                current = candidate
            if len(self._timed_chunk_text(parsed.text, current)) > self.config.max_input_chars:
                warnings.append(
                    f"timed_text_segment_exceeds_budget:line={segment.source_line}:"
                    f"chars={len(self._timed_chunk_text(parsed.text, current))}"
                )
        if current:
            if len(chunks) >= max_chunks:
                warnings.append(
                    f"timed_text_chunk_limit_reached:max_chunks={max_chunks}:"
                    f"remaining_segments={len(current)}"
                )
            else:
                chunks.append(
                    self._prepared_timed_chunk(
                        parsed.text,
                        current,
                        len(chunks) + 1,
                        parsed.timed_text_format,
                    )
                )
        if len(chunks) > 1:
            warnings.append(f"timed_text_split_into_chunks:count={len(chunks)}")
        return chunks, warnings

    def chunk_material(self, text: str, *, chunk_limit: int | None = None) -> TextChunkingResult:
        max_chunks = self.config.max_chunks_per_unit
        if chunk_limit is not None:
            max_chunks = min(max_chunks, max(1, chunk_limit))
        return chunk_text_with_ranges(
            text,
            max_chars=self.config.max_input_chars,
            overlap_chars=self.config.overlap_chars,
            max_chunks=max_chunks,
        )

    def _chunk_result(
        self,
        *,
        unit: ExtractionUnit,
        season_id: str,
        chunk_id: str,
        text_range: TextRange,
        timed_segments: list[TimedTextSegment],
        extraction_stage: ExtractionArtifactStage,
        extraction_run_id: str,
        run_type: str,
        payload: dict[str, Any],
        result: FormalExtractionJsonResult,
        warnings: list[str],
    ) -> ChunkExtractionResult:
        time_range = self._time_range(timed_segments)
        material_ref = unit.material_ref.model_copy(
            update={"text_range": text_range, "time_range": time_range}
        )
        evidence_locator = {
            "relative_path": material_ref.relative_path,
            "text_range": text_range.model_dump(mode="json"),
        }
        if timed_segments and time_range is not None:
            evidence_locator.update(
                {
                    "time_range": time_range.model_dump(mode="json"),
                    "timed_text_segments": [
                        {
                            "index": segment.index,
                            "source_line": segment.source_line,
                            "start_seconds": segment.start_seconds,
                            "end_seconds": segment.end_seconds,
                            "speaker": segment.speaker,
                            "text": segment.text,
                            "raw_text": segment.raw_text,
                        }
                        for segment in timed_segments
                    ],
                }
            )
            source_lines = [
                segment.source_line
                for segment in timed_segments
                if segment.source_line is not None
            ]
            if source_lines:
                evidence_locator["source_line_start"] = source_lines[0]
                evidence_locator["source_line_end"] = source_lines[-1]
        evidence = EvidenceRef(
            evidence_id=f"evidence_{chunk_id}",
            material_ref=material_ref,
            unit_ref=unit.unit_id,
            locator=evidence_locator,
            quote_policy="reference_only",
            metadata={
                "media_type": MediaType.TEXT.value,
                "unit_kind": unit.unit_kind,
                "speaker_policy": "explicit_only",
            },
        )
        source_trace = SourceTrace(
            material_refs=[material_ref],
            unit_refs=[unit.unit_id],
            derived_artifact_refs=list(unit.derived_refs),
            evidence_refs=[evidence],
            source_breakdown={"materials": 1, "units": 1, "text": 1},
        )
        fallback_evidence = self._fallback_evidence(material_ref.relative_path, text_range, timed_segments)
        evidence_refs = self._string_list(payload.get("evidence_refs"))
        if fallback_evidence not in evidence_refs:
            evidence_refs.append(fallback_evidence)
        relationships = payload.get("relationship_interactions", payload.get("relationships"))
        return ChunkExtractionResult(
            season_id=season_id,
            episode_id=unit.episode_id,
            chunk_id=chunk_id,
            extraction_stage=extraction_stage,
            extraction_run_id=extraction_run_id,
            run_type=run_type,
            source_path=material_ref.relative_path,
            source_kind=MediaType.TEXT.value,
            source_trace=source_trace.model_dump(mode="json"),
            source_counts={
                "materials": 1,
                "units": 1,
                "text_ranges": 1,
                "timed_text_segments": len(timed_segments),
                "transcript_segments": (
                    len(timed_segments) if unit.unit_kind == "transcript_text" else 0
                ),
            },
            aggregation_warnings=list(warnings),
            model_metadata=result.model_metadata,
            token_usage=result.token_usage,
            estimated_context_tokens=result.estimated_context_tokens,
            requested_output_tokens=result.requested_output_tokens,
            finish_reason=result.finish_reason,
            facts=self._string_list(payload.get("facts")),
            behavior_traits=self._string_list(payload.get("behavior_traits")),
            dialogue_style=self._string_list(payload.get("dialogue_style")),
            relationship_interactions=self._string_list(relationships),
            conflicts=self._string_list(payload.get("conflicts")),
            character_state_changes=self._string_list(payload.get("character_state_changes")),
            insight_summary=str(payload.get("insight_summary", "")).strip(),
            evidence_refs=evidence_refs,
        )

    def _prepared_timed_chunk(
        self,
        source_text: str,
        segments: list[TimedTextSegment],
        index: int,
        timed_text_format: str,
    ) -> PreparedTextChunk:
        return PreparedTextChunk(
            index=index,
            text=self._timed_chunk_text(source_text, segments),
            start_offset=segments[0].start_offset,
            end_offset=segments[-1].end_offset,
            timed_text_format=timed_text_format,
            timed_segments=list(segments),
        )

    @staticmethod
    def _timed_chunk_text(source_text: str, segments: list[TimedTextSegment]) -> str:
        if not segments:
            return ""
        return source_text[segments[0].start_offset : segments[-1].end_offset]

    @staticmethod
    def _time_range(segments: list[TimedTextSegment]) -> TimeRange | None:
        if not segments:
            return None
        return TimeRange(
            start_seconds=segments[0].start_seconds,
            end_seconds=max(segment.end_seconds for segment in segments),
        )

    @staticmethod
    def _source_locator(chunk: PreparedTextChunk) -> str:
        if not chunk.timed_segments:
            return f"text={chunk.start_offset}:{chunk.end_offset}"
        parts: list[str] = []
        source_lines = [
            segment.source_line
            for segment in chunk.timed_segments
            if segment.source_line is not None
        ]
        if source_lines:
            parts.append(f"lines={source_lines[0]}-{source_lines[-1]}")
        parts.append(
            f"time={chunk.timed_segments[0].start_seconds:.3f}-"
            f"{max(segment.end_seconds for segment in chunk.timed_segments):.3f}"
        )
        return ";".join(parts)

    @staticmethod
    def _evidence_guidance(chunk: PreparedTextChunk) -> str:
        if not chunk.timed_segments:
            return "只依据当前文本范围提取；证据不足时保留不确定性。"
        if chunk.timed_text_format == "transcript":
            return (
                "保留每段转写文本的时间范围。speaker=unknown 表示转写结果没有提供说话人，"
                "不得根据台词内容猜测或强行归属；仅可使用显式 speaker 字段。"
            )
        return (
            "保留每条字幕的时间与源行号。speaker=unknown 表示素材没有提供说话人，"
            "不得根据台词内容猜测或强行归属；仅可使用显式 speaker 字段。"
        )

    @staticmethod
    def _fallback_evidence(
        relative_path: str,
        text_range: TextRange,
        timed_segments: list[TimedTextSegment],
    ) -> str:
        if timed_segments:
            evidence = (
                f"{relative_path}#time={timed_segments[0].start_seconds:.3f}-"
                f"{max(segment.end_seconds for segment in timed_segments):.3f}"
            )
            source_lines = [
                segment.source_line
                for segment in timed_segments
                if segment.source_line is not None
            ]
            if source_lines:
                evidence += f"&lines={source_lines[0]}-{source_lines[-1]}"
            return evidence
        return f"{relative_path}#text={text_range.start_offset}-{text_range.end_offset}"

    def _source_path(self, source_root: Path, unit: ExtractionUnit) -> Path:
        root = source_root.resolve()
        path = (root / unit.material_ref.relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("text source path escapes source root") from exc
        if not path.is_file():
            raise ValueError(f"text source does not exist: {unit.material_ref.relative_path}")
        return path

    def _decode_text(self, raw: bytes, path: Path) -> tuple[str, str]:
        for encoding in TEXT_DECODE_ENCODINGS:
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise ValueError(f"text material encoding is unsupported: {path.name}")

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
