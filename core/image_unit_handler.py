from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.extraction_ai import FormalExtractionJsonResult, call_formal_image_json_model
from core.extraction_plan import EvidenceRef, ExtractionUnit, MediaType, SourceTrace
from core.models import ChunkExtractionResult, ExtractionArtifactStage
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, ModelMessage, render_prompt_texts
from utils.cloud_model_presets import provider_requires_aliyun_extra_body
from utils.media_types import SUPPORTED_STATIC_IMAGE_SUFFIXES


IMAGE_UNIT_KINDS = frozenset({"image_source", "image_page"})
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
DEFAULT_IMAGE_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_IMAGE_OUTPUT_TOKENS_PER_IMAGE = 2_048
ModelJsonCall = Callable[[ModelCallRequest], FormalExtractionJsonResult]


@dataclass(frozen=True, slots=True)
class ImageUnitHandlerConfig:
    provider: str = "custom"
    max_image_bytes: int = DEFAULT_IMAGE_MAX_BYTES
    max_output_tokens_per_image: int = DEFAULT_IMAGE_OUTPUT_TOKENS_PER_IMAGE


@dataclass(frozen=True, slots=True)
class ParsedImageMaterial:
    data_url: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImageUnitExecutionResult:
    chunks: list[ChunkExtractionResult]
    warnings: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)


class ImageUnitHandler:
    def __init__(
        self,
        config: ImageUnitHandlerConfig | None = None,
        *,
        model_call: ModelJsonCall = call_formal_image_json_model,
    ) -> None:
        self.config = config or ImageUnitHandlerConfig()
        self._model_call = model_call

    def supports(self, unit: ExtractionUnit) -> bool:
        return (
            unit.media_type == MediaType.IMAGE
            and unit.unit_kind in IMAGE_UNIT_KINDS
            and Path(unit.material_ref.relative_path).suffix.lower()
            in SUPPORTED_STATIC_IMAGE_SUFFIXES
        )

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
    ) -> ImageUnitExecutionResult:
        if not self.supports(unit):
            raise ValueError(f"unsupported image extraction unit: {unit.unit_kind}")

        source_path = self._material_path(materials_root, unit)
        material = self.parse_material(source_path)
        chunk_id = f"{unit.unit_id}_image_0001"
        request = self._build_request(
            unit=unit,
            season_id=season_id,
            chunk_id=chunk_id,
            material=material,
            extraction_stage=extraction_stage,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
        )
        result = self._model_call(request)
        chunk = self._chunk_result(
            unit=unit,
            season_id=season_id,
            chunk_id=chunk_id,
            extraction_stage=extraction_stage,
            extraction_run_id=extraction_run_id,
            run_type=run_type,
            material=material,
            payload=result.payload,
            result=result,
        )
        return ImageUnitExecutionResult(
            chunks=[chunk],
            warnings=list(material.warnings),
            token_usage=dict(result.token_usage),
        )

    def parse_material(self, path: Path) -> ParsedImageMaterial:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_STATIC_IMAGE_SUFFIXES:
            raise ValueError(f"unsupported static image suffix: {suffix or '<none>'}")
        size_bytes = path.stat().st_size
        if size_bytes > self.config.max_image_bytes:
            raise ValueError(
                "image material exceeds byte limit:"
                f"size={size_bytes},limit={self.config.max_image_bytes}"
            )
        raw = path.read_bytes()
        if not raw:
            raise ValueError("image material is empty")
        self._validate_signature(suffix, raw)
        width, height = self._image_dimensions(suffix, raw)
        mime_type = IMAGE_MIME_TYPES[suffix]
        encoded = base64.b64encode(raw).decode("ascii")
        return ParsedImageMaterial(
            data_url=f"data:{mime_type};base64,{encoded}",
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
        )

    def _build_request(
        self,
        *,
        unit: ExtractionUnit,
        season_id: str,
        chunk_id: str,
        material: ParsedImageMaterial,
        extraction_stage: ExtractionArtifactStage,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
    ) -> ModelCallRequest:
        purpose = (
            "preview_image_unit_extraction"
            if extraction_stage == ExtractionArtifactStage.PREVIEW
            else "formal_image_unit_extraction"
        )
        system_prompt, user_text = render_prompt_texts(
            purpose=purpose,
            variables={
                "season_id": season_id,
                "episode_id": unit.episode_id,
                "chunk_id": chunk_id,
                "source_path": unit.material_ref.relative_path,
                "content_form": unit.content_form.value,
                "source_locator": self._source_locator(unit),
                "expected_output_tokens_per_image": self.config.max_output_tokens_per_image,
            },
        )
        return ModelCallRequest(
            purpose=purpose,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            messages=[
                ModelMessage(role="system", content=system_prompt),
                ModelMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": material.data_url}},
                    ],
                ),
            ],
            temperature=0.2,
            max_tokens=self.config.max_output_tokens_per_image,
            stream=False,
            timeout_seconds=240,
            response_format={"type": "json_object"},
            extra_body=self._image_model_extra_body(),
            metadata={
                "stage": extraction_stage.value,
                "season_id": season_id,
                "episode_id": unit.episode_id,
                "chunk_id": chunk_id,
                "source_path": unit.material_ref.relative_path,
                "media_type": MediaType.IMAGE.value,
                "content_form": unit.content_form.value,
                "unit_kind": unit.unit_kind,
                "image_mime_type": material.mime_type,
                "image_size_bytes": material.size_bytes,
                "output_budget_basis": "per_image",
                "output_budget_source": "internal_default",
            },
        )

    def _chunk_result(
        self,
        *,
        unit: ExtractionUnit,
        season_id: str,
        chunk_id: str,
        extraction_stage: ExtractionArtifactStage,
        extraction_run_id: str,
        run_type: str,
        material: ParsedImageMaterial,
        payload: dict[str, Any],
        result: FormalExtractionJsonResult,
    ) -> ChunkExtractionResult:
        material_ref = unit.material_ref
        locator: dict[str, Any] = {
            "relative_path": material_ref.relative_path,
            "mime_type": material.mime_type,
            "size_bytes": material.size_bytes,
        }
        if material.width is not None and material.height is not None:
            locator["pixel_size"] = {"width": material.width, "height": material.height}
        if material_ref.page_range is not None:
            locator["page_range"] = material_ref.page_range.model_dump(mode="json")
        if material_ref.region is not None:
            locator["region"] = material_ref.region.model_dump(mode="json")
        evidence = EvidenceRef(
            evidence_id=f"evidence_{chunk_id}",
            material_ref=material_ref,
            unit_ref=unit.unit_id,
            locator=locator,
            quote_policy="reference_only",
            metadata={
                "media_type": MediaType.IMAGE.value,
                "unit_kind": unit.unit_kind,
            },
        )
        source_trace = SourceTrace(
            material_refs=[material_ref],
            unit_refs=[unit.unit_id],
            derived_artifact_refs=list(unit.derived_refs),
            evidence_refs=[evidence],
            source_breakdown={"materials": 1, "units": 1, "image": 1},
        )
        fallback_evidence = self._fallback_evidence(unit)
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
            source_kind=MediaType.IMAGE.value,
            source_trace=source_trace.model_dump(mode="json"),
            source_counts={
                "materials": 1,
                "units": 1,
                "images": 1,
                "pages": 1 if material_ref.page_range is not None else 0,
                "regions": 1 if material_ref.region is not None else 0,
            },
            aggregation_warnings=list(material.warnings),
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
            raise ValueError("image material path escapes materials root") from exc
        if not path.is_file():
            raise ValueError(f"image material does not exist: {unit.material_ref.relative_path}")
        return path

    def _image_model_extra_body(self) -> dict[str, Any]:
        if provider_requires_aliyun_extra_body(self.config.provider):
            return {"enable_thinking": False}
        return {}

    @staticmethod
    def _source_locator(unit: ExtractionUnit) -> str:
        parts: list[str] = []
        page_range = unit.material_ref.page_range
        if page_range is not None and page_range.start_page is not None:
            parts.append(f"page={page_range.start_page}")
        region = unit.material_ref.region
        if region is not None:
            parts.append(
                "region="
                f"{region.x},{region.y},{region.width},{region.height},{region.unit}"
            )
        return ";".join(parts) or "full_image"

    @staticmethod
    def _fallback_evidence(unit: ExtractionUnit) -> str:
        evidence = unit.material_ref.relative_path
        page_range = unit.material_ref.page_range
        if page_range is not None and page_range.start_page is not None:
            evidence += f"#page={page_range.start_page}"
        else:
            evidence += "#image"
        region = unit.material_ref.region
        if region is not None:
            evidence += (
                "&region="
                f"{region.x},{region.y},{region.width},{region.height},{region.unit}"
            )
        return evidence

    @staticmethod
    def _validate_signature(suffix: str, raw: bytes) -> None:
        valid = False
        if suffix == ".png":
            valid = raw.startswith(b"\x89PNG\r\n\x1a\n")
        elif suffix in {".jpg", ".jpeg"}:
            valid = raw.startswith(b"\xff\xd8\xff")
        elif suffix == ".webp":
            valid = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
        if not valid:
            raise ValueError(f"image material signature does not match suffix: {suffix}")

    @staticmethod
    def _image_dimensions(suffix: str, raw: bytes) -> tuple[int | None, int | None]:
        if suffix == ".png" and len(raw) >= 24:
            return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
        if suffix in {".jpg", ".jpeg"}:
            return ImageUnitHandler._jpeg_dimensions(raw)
        return None, None

    @staticmethod
    def _jpeg_dimensions(raw: bytes) -> tuple[int | None, int | None]:
        offset = 2
        start_of_frame_markers = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while offset + 3 < len(raw):
            if raw[offset] != 0xFF:
                offset += 1
                continue
            while offset < len(raw) and raw[offset] == 0xFF:
                offset += 1
            if offset >= len(raw):
                break
            marker = raw[offset]
            offset += 1
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(raw):
                break
            segment_length = int.from_bytes(raw[offset : offset + 2], "big")
            if segment_length < 2 or offset + segment_length > len(raw):
                break
            if marker in start_of_frame_markers and segment_length >= 7:
                height = int.from_bytes(raw[offset + 3 : offset + 5], "big")
                width = int.from_bytes(raw[offset + 5 : offset + 7], "big")
                return width, height
            offset += segment_length
        return None, None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
