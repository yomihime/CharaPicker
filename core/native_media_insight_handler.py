from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.extraction_ai import (
    FormalExtractionJsonResult,
    call_formal_audio_json_model,
    call_formal_video_json_model,
)
from core.extraction_plan import EvidenceRef, ExtractionUnit, MediaType, SourceTrace
from core.models import ChunkExtractionResult, ExtractionArtifactStage
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, ModelMessage, render_prompt_texts
from utils.cloud_model_presets import (
    CloudCapability,
    cloud_model_provider,
    provider_requires_aliyun_extra_body,
    provider_supports_capability,
)


NATIVE_MEDIA_UNIT_KINDS = frozenset({"audio_source", "video_chunk"})
DEFAULT_NATIVE_MEDIA_OUTPUT_TOKENS = 2_048
NATIVE_MEDIA_INSIGHT_PROMPT = "formal_native_media_insight"
NATIVE_AUDIO_UNSUPPORTED_REASON = "model_audio_understanding_not_supported"
NATIVE_VIDEO_UNSUPPORTED_REASON = "model_native_video_not_supported"
NATIVE_VIDEO_BACKEND_UNSUPPORTED_REASON = "native_video_backend_not_supported"

ModelJsonCall = Callable[[ModelCallRequest], FormalExtractionJsonResult]


@dataclass(frozen=True, slots=True)
class NativeMediaInsightHandlerConfig:
    provider: str
    video_fps: float = 1.0
    max_output_tokens: int = DEFAULT_NATIVE_MEDIA_OUTPUT_TOKENS


@dataclass(frozen=True, slots=True)
class NativeMediaInsightSupport:
    supported: bool
    capability: CloudCapability | str = ""
    reason: str = ""
    backend: str = ""


@dataclass(frozen=True, slots=True)
class NativeMediaInsightExecutionResult:
    chunks: list[ChunkExtractionResult]
    warnings: list[str]
    token_usage: dict[str, int]
    support: NativeMediaInsightSupport


class NativeMediaInsightHandler:
    def __init__(
        self,
        config: NativeMediaInsightHandlerConfig,
        *,
        audio_model_call: ModelJsonCall = call_formal_audio_json_model,
        video_model_call: ModelJsonCall = call_formal_video_json_model,
    ) -> None:
        self.config = config
        self._audio_model_call = audio_model_call
        self._video_model_call = video_model_call

    @staticmethod
    def can_consider(unit: ExtractionUnit) -> bool:
        return (
            unit.media_type in {MediaType.AUDIO, MediaType.VIDEO}
            and unit.unit_kind in NATIVE_MEDIA_UNIT_KINDS
        )

    def supports(self, unit: ExtractionUnit) -> bool:
        return self.support_status(unit).supported

    def support_status(self, unit: ExtractionUnit) -> NativeMediaInsightSupport:
        if not self.can_consider(unit):
            return NativeMediaInsightSupport(False, reason="native_media_handler_not_available")

        provider = cloud_model_provider(self.config.provider)
        if unit.media_type == MediaType.AUDIO:
            backend = provider.backend_for("audio")
            if not provider_supports_capability(self.config.provider, "audio_understanding"):
                return NativeMediaInsightSupport(
                    False,
                    reason=NATIVE_AUDIO_UNSUPPORTED_REASON,
                    backend=backend,
                )
            if backend not in {"openai_compatible", "dashscope"}:
                return NativeMediaInsightSupport(
                    False,
                    capability="audio_understanding",
                    reason=NATIVE_AUDIO_UNSUPPORTED_REASON,
                    backend=backend,
                )
            return NativeMediaInsightSupport(
                True,
                capability="audio_understanding",
                backend=backend,
            )

        backend = provider.backend_for("video")
        capability: CloudCapability | str = ""
        if provider_supports_capability(self.config.provider, "native_video"):
            capability = "native_video"
        elif provider_supports_capability(self.config.provider, "video_audio_understanding"):
            capability = "video_audio_understanding"
        else:
            return NativeMediaInsightSupport(
                False,
                reason=NATIVE_VIDEO_UNSUPPORTED_REASON,
                backend=backend,
            )
        if backend != "dashscope":
            return NativeMediaInsightSupport(
                False,
                capability=capability,
                reason=NATIVE_VIDEO_BACKEND_UNSUPPORTED_REASON,
                backend=backend,
            )
        return NativeMediaInsightSupport(True, capability=capability, backend=backend)

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
    ) -> NativeMediaInsightExecutionResult:
        support = self.support_status(unit)
        if not support.supported:
            raise ValueError(f"unsupported native media insight unit: {support.reason}")

        source_path = self._material_path(materials_root, unit)
        chunk_id = f"{unit.unit_id}_native_media_0001"
        request = self._build_request(
            unit=unit,
            season_id=season_id,
            chunk_id=chunk_id,
            source_path=source_path,
            extraction_stage=extraction_stage,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            support=support,
        )
        result = self._model_call_for(unit)(request)
        chunk = self._chunk_result(
            unit=unit,
            season_id=season_id,
            chunk_id=chunk_id,
            extraction_stage=extraction_stage,
            extraction_run_id=extraction_run_id,
            run_type=run_type,
            source_path=source_path,
            payload=result.payload,
            result=result,
            support=support,
        )
        return NativeMediaInsightExecutionResult(
            chunks=[chunk],
            warnings=[],
            token_usage=dict(result.token_usage),
            support=support,
        )

    def _build_request(
        self,
        *,
        unit: ExtractionUnit,
        season_id: str,
        chunk_id: str,
        source_path: Path,
        extraction_stage: ExtractionArtifactStage,
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        support: NativeMediaInsightSupport,
    ) -> ModelCallRequest:
        system_prompt, user_text = render_prompt_texts(
            purpose=NATIVE_MEDIA_INSIGHT_PROMPT,
            variables={
                "season_id": season_id,
                "episode_id": unit.episode_id,
                "chunk_id": chunk_id,
                "source_path": unit.material_ref.relative_path,
                "media_type": unit.media_type.value,
                "content_form": unit.content_form.value,
                "unit_kind": unit.unit_kind,
                "native_capability": support.capability,
            },
        )
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        media_url = f"file://{source_path.resolve().as_posix()}"
        if unit.media_type == MediaType.AUDIO:
            content_parts.append({"type": "audio_url", "audio_url": {"url": media_url}})
        else:
            content_parts.append({"video": media_url, "fps": self.config.video_fps})

        return ModelCallRequest(
            purpose=NATIVE_MEDIA_INSIGHT_PROMPT,
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            messages=[
                ModelMessage(role="system", content=system_prompt),
                ModelMessage(role="user", content=content_parts),
            ],
            temperature=0.2,
            max_tokens=self.config.max_output_tokens,
            stream=False,
            timeout_seconds=240,
            response_format={"type": "json_object"},
            extra_body=self._native_model_extra_body(),
            metadata={
                "stage": extraction_stage.value,
                "season_id": season_id,
                "episode_id": unit.episode_id,
                "chunk_id": chunk_id,
                "source_path": unit.material_ref.relative_path,
                "media_type": unit.media_type.value,
                "content_form": unit.content_form.value,
                "unit_kind": unit.unit_kind,
                "native_media_insight": True,
                "native_media_capability": support.capability,
                "native_media_backend": support.backend,
                "transcript_policy": "supplement_only",
                "does_not_replace_transcript": True,
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
        source_path: Path,
        payload: dict[str, Any],
        result: FormalExtractionJsonResult,
        support: NativeMediaInsightSupport,
    ) -> ChunkExtractionResult:
        material_ref = unit.material_ref
        locator = {
            "relative_path": material_ref.relative_path,
            "media_type": unit.media_type.value,
            "native_media_capability": support.capability,
            "file_size_bytes": source_path.stat().st_size,
        }
        if material_ref.time_range is not None:
            locator["time_range"] = material_ref.time_range.model_dump(mode="json")
        evidence = EvidenceRef(
            evidence_id=f"evidence_{chunk_id}",
            material_ref=material_ref,
            unit_ref=unit.unit_id,
            locator=locator,
            quote_policy="reference_only",
            metadata={
                "media_type": unit.media_type.value,
                "unit_kind": unit.unit_kind,
                "native_media_insight": True,
                "transcript_policy": "supplement_only",
            },
        )
        source_trace = SourceTrace(
            material_refs=[material_ref],
            unit_refs=[unit.unit_id],
            derived_artifact_refs=[],
            evidence_refs=[evidence],
            source_breakdown={
                "materials": 1,
                "units": 1,
                unit.media_type.value: 1,
                "native_media_insights": 1,
            },
            metadata={
                "native_media_insight": True,
                "native_media_capability": support.capability,
                "transcript_policy": "supplement_only",
            },
        )
        evidence_refs = self._string_list(payload.get("evidence_refs"))
        fallback_evidence = f"{material_ref.relative_path}#native_media"
        if fallback_evidence not in evidence_refs:
            evidence_refs.append(fallback_evidence)
        relationships = payload.get("relationship_interactions", payload.get("relationships"))
        facts = self._native_fact_list(payload)
        model_metadata = {
            **result.model_metadata,
            "native_media_insight": True,
            "native_media_capability": support.capability,
            "native_media_backend": support.backend,
            "transcript_policy": "supplement_only",
            "does_not_replace_transcript": True,
        }
        return ChunkExtractionResult(
            season_id=season_id,
            episode_id=unit.episode_id,
            chunk_id=chunk_id,
            extraction_stage=extraction_stage,
            extraction_run_id=extraction_run_id,
            run_type=run_type,
            source_path=material_ref.relative_path,
            source_kind=unit.media_type.value,
            source_trace=source_trace.model_dump(mode="json"),
            source_counts={
                "materials": 1,
                "units": 1,
                unit.media_type.value: 1,
                "native_media_insights": 1,
            },
            model_metadata=model_metadata,
            token_usage=result.token_usage,
            estimated_context_tokens=result.estimated_context_tokens,
            requested_output_tokens=result.requested_output_tokens,
            finish_reason=result.finish_reason,
            facts=facts,
            behavior_traits=[
                *self._string_list(payload.get("behavior_traits")),
                *self._prefixed_list("tone", payload.get("tone")),
            ],
            dialogue_style=self._string_list(payload.get("dialogue_style")),
            relationship_interactions=self._string_list(relationships),
            conflicts=self._string_list(payload.get("conflicts")),
            character_state_changes=self._string_list(payload.get("character_state_changes")),
            insight_summary=self._insight_summary(payload),
            evidence_refs=evidence_refs,
        )

    def _material_path(self, materials_root: Path, unit: ExtractionUnit) -> Path:
        root = materials_root.resolve()
        path = (root / unit.material_ref.relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("native media material path escapes materials root") from exc
        if not path.is_file():
            raise ValueError(
                f"native media material does not exist: {unit.material_ref.relative_path}"
            )
        return path

    def _model_call_for(self, unit: ExtractionUnit) -> ModelJsonCall:
        if unit.media_type == MediaType.AUDIO:
            return self._audio_model_call
        return self._video_model_call

    def _native_model_extra_body(self) -> dict[str, Any]:
        if provider_requires_aliyun_extra_body(self.config.provider):
            return {"enable_thinking": False}
        return {}

    @classmethod
    def _native_fact_list(cls, payload: dict[str, Any]) -> list[str]:
        facts = cls._string_list(payload.get("facts"))
        for key, label in (
            ("auditory_summary", "auditory_summary"),
            ("visual_summary", "visual_summary"),
            ("environment_sounds", "environment_sounds"),
            ("music", "music"),
            ("offscreen_voices", "offscreen_voices"),
        ):
            facts.extend(cls._prefixed_list(label, payload.get(key)))
        return facts

    @classmethod
    def _insight_summary(cls, payload: dict[str, Any]) -> str:
        summary = str(payload.get("insight_summary", "")).strip()
        if summary:
            return summary
        summaries = [
            *cls._string_list(payload.get("auditory_summary")),
            *cls._string_list(payload.get("visual_summary")),
        ]
        return "\n".join(summaries).strip()

    @classmethod
    def _prefixed_list(cls, label: str, value: Any) -> list[str]:
        return [f"{label}: {item}" for item in cls._string_list(value)]

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if not isinstance(value, list):
            return []
        output: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                output.append(item.strip())
            elif isinstance(item, dict):
                output.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        return output
