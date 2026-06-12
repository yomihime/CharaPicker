from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExtractionPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MediaType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    TEXT = "text"


class ContentForm(str, Enum):
    UNKNOWN = "unknown"
    ANIME = "anime"
    MANGA = "manga"
    NOVEL = "novel"
    SCRIPT = "script"
    SETTING_BOOK = "setting_book"
    AUDIO_DRAMA = "audio_drama"
    VIDEO_PROGRAM = "video_program"
    IMAGE_SET = "image_set"
    MIXED = "mixed"


class MaterialOrigin(str, Enum):
    RAW = "raw"
    MATERIAL = "material"
    DERIVED = "derived"
    AGGREGATED = "aggregated"


class FormalExtractionMode(str, Enum):
    FULL = "full"
    CLEAN = "clean"
    FAST = "fast"


class DerivedArtifactKind(str, Enum):
    TRANSCRIPT = "transcript"
    OCR_TEXT = "ocr_text"
    TEXT_CHUNK = "text_chunk"
    FRAME_SAMPLE = "frame_sample"
    AUDIO_SEGMENT = "audio_segment"
    SUMMARY = "summary"
    SEMANTIC_INDEX = "semantic_index"


class DerivedArtifactStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    MISSING = "missing"
    FAILED = "failed"
    STALE = "stale"
    SKIPPED = "skipped"


class TimeRange(ExtractionPlanModel):
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)


class PageRange(ExtractionPlanModel):
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)


class TextRange(ExtractionPlanModel):
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    chapter: str = ""
    section: str = ""


class RegionRef(ExtractionPlanModel):
    x: float | None = Field(default=None, ge=0)
    y: float | None = Field(default=None, ge=0)
    width: float | None = Field(default=None, ge=0)
    height: float | None = Field(default=None, ge=0)
    unit: str = "normalized"


class MaterialRef(ExtractionPlanModel):
    material_id: str
    relative_path: str
    source_media_type: MediaType
    content_form: ContentForm = ContentForm.UNKNOWN
    origin: MaterialOrigin = MaterialOrigin.MATERIAL
    fingerprint: str = ""
    time_range: TimeRange | None = None
    page_range: PageRange | None = None
    text_range: TextRange | None = None
    region: RegionRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionUnit(ExtractionPlanModel):
    unit_id: str
    episode_id: str
    media_type: MediaType
    content_form: ContentForm = ContentForm.UNKNOWN
    material_ref: MaterialRef
    origin: MaterialOrigin = MaterialOrigin.MATERIAL
    unit_kind: str = ""
    derived_refs: list[str] = Field(default_factory=list)
    budget_hint: dict[str, Any] = Field(default_factory=dict)
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    context_policy: dict[str, Any] = Field(default_factory=dict)
    handler_options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodePlan(ExtractionPlanModel):
    season_id: str
    episode_id: str
    display_title: str = ""
    sort_key: str = ""
    content_forms: list[ContentForm] = Field(default_factory=list)
    units: list[ExtractionUnit] = Field(default_factory=list)
    derived_artifact_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DerivedArtifact(ExtractionPlanModel):
    artifact_id: str
    derived_kind: DerivedArtifactKind
    content_kind: MediaType
    source_refs: list[MaterialRef] = Field(default_factory=list)
    artifact_path: str = ""
    coverage: dict[str, Any] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)
    status: DerivedArtifactStatus = DerivedArtifactStatus.PENDING
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(ExtractionPlanModel):
    evidence_id: str
    material_ref: MaterialRef | None = None
    unit_ref: str = ""
    derived_artifact_ref: str = ""
    aggregation_ref: str = ""
    locator: dict[str, Any] = Field(default_factory=dict)
    quote_policy: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceTrace(ExtractionPlanModel):
    material_refs: list[MaterialRef] = Field(default_factory=list)
    unit_refs: list[str] = Field(default_factory=list)
    derived_artifact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    aggregation_refs: list[str] = Field(default_factory=list)
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormalExtractionRunPlan(ExtractionPlanModel):
    project_id: str
    run_id: str = Field(default_factory=lambda: f"run-{uuid4().hex[:12]}")
    mode: FormalExtractionMode = FormalExtractionMode.FULL
    plan_schema_version: int = 1
    media_types: list[MediaType] = Field(default_factory=list)
    content_forms: list[ContentForm] = Field(default_factory=list)
    episodes: list[EpisodePlan] = Field(default_factory=list)
    derived_artifacts: list[DerivedArtifact] = Field(default_factory=list)
    model_profile_id: str = ""
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    context_policy: dict[str, Any] = Field(default_factory=dict)
    failure_policy: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def all_units(self) -> list[ExtractionUnit]:
        return [unit for episode in self.episodes for unit in episode.units]

    @property
    def unit_count(self) -> int:
        return len(self.all_units)
