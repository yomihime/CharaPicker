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
from core.extraction_plan import EvidenceRef, ExtractionUnit, MediaType, SourceTrace, TextRange
from core.models import ChunkExtractionResult, ExtractionArtifactStage
from utils.ai_model_middleware import ModelBackend, ModelCallRequest
from utils.chunker import TextChunkingResult, chunk_text_with_ranges


TEXT_DOCUMENT_UNIT_KINDS = frozenset({"document_text", "controlled_json_text"})
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
        return unit.media_type == MediaType.TEXT and unit.unit_kind in TEXT_DOCUMENT_UNIT_KINDS

    def execute(
        self,
        *,
        materials_root: Path,
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

        source_path = self._material_path(materials_root, unit)
        parsed = self.parse_material(source_path)
        chunking = self.chunk_material(parsed.text, chunk_limit=chunk_limit)
        warnings = [*parsed.warnings, *chunking.warnings]
        output: list[ChunkExtractionResult] = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for text_chunk in chunking.chunks:
            chunk_id = f"{unit.unit_id}_text_{text_chunk.index:04d}"
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
                    "text_range": (
                        f"{text_chunk.start_offset}:{text_chunk.end_offset}"
                    ),
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

    def parse_material(self, path: Path) -> ParsedTextMaterial:
        suffix = path.suffix.lower()
        if suffix not in TEXT_DOCUMENT_SUFFIXES:
            raise ValueError(f"unsupported text material suffix: {suffix or '<none>'}")
        raw = path.read_bytes()
        text, encoding = self._decode_text(raw, path)
        warnings: list[str] = []
        if encoding not in {"utf-8", "utf-8-sig"}:
            warnings.append(f"text_decoded_with_fallback:{encoding}")
        if suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"controlled JSON text is invalid: {path.name}") from exc
            if not isinstance(payload, (dict, list)):
                raise ValueError("controlled JSON text must contain an object or array")
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        return ParsedTextMaterial(text=text, encoding=encoding, warnings=warnings)

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
        extraction_stage: ExtractionArtifactStage,
        extraction_run_id: str,
        run_type: str,
        payload: dict[str, Any],
        result: FormalExtractionJsonResult,
        warnings: list[str],
    ) -> ChunkExtractionResult:
        material_ref = unit.material_ref.model_copy(update={"text_range": text_range})
        evidence_locator = {
            "relative_path": material_ref.relative_path,
            "text_range": text_range.model_dump(mode="json"),
        }
        evidence = EvidenceRef(
            evidence_id=f"evidence_{chunk_id}",
            material_ref=material_ref,
            unit_ref=unit.unit_id,
            locator=evidence_locator,
            quote_policy="reference_only",
            metadata={"media_type": MediaType.TEXT.value},
        )
        source_trace = SourceTrace(
            material_refs=[material_ref],
            unit_refs=[unit.unit_id],
            derived_artifact_refs=list(unit.derived_refs),
            evidence_refs=[evidence],
            source_breakdown={"materials": 1, "units": 1, "text": 1},
        )
        fallback_evidence = (
            f"{material_ref.relative_path}#text="
            f"{text_range.start_offset}-{text_range.end_offset}"
        )
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
            source_counts={"materials": 1, "units": 1, "text_ranges": 1},
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

    def _material_path(self, materials_root: Path, unit: ExtractionUnit) -> Path:
        root = materials_root.resolve()
        path = (root / unit.material_ref.relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("text material path escapes materials root") from exc
        if not path.is_file():
            raise ValueError(f"text material does not exist: {unit.material_ref.relative_path}")
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
