from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ExtractionMode(str, Enum):
    PREVIEW = "preview"
    FULL = "full"


class SourceProcessingPreset(str, Enum):
    ORIGINAL = "original"
    SEGMENT_TRANSCODE = "segment_transcode"
    SEGMENT_ONLY = "segment_only"
    TRANSCODE_ONLY = "transcode_only"


class SourceSegmentMode(str, Enum):
    TIME = "time"
    COUNT = "count"


class InsightStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    WARNING = "warning"


class SourceProcessingConfig(BaseModel):
    preset: SourceProcessingPreset = SourceProcessingPreset.ORIGINAL
    trim_enabled: bool = False
    trim_start: str = "00:00"
    trim_end: str = "00:00"
    transcode_enabled: bool = False
    codec: str = "H.264"
    resolution: str = "540p"
    segment_enabled: bool = False
    segment_mode: SourceSegmentMode = SourceSegmentMode.TIME
    segment_time: str = "00:02:00"
    segment_count: int = 4


class ProjectConfig(BaseModel):
    project_id: str = Field(default_factory=lambda: f"project-{uuid4().hex[:8]}")
    name: str = "Untitled Project"
    target_characters: list[str] = Field(default_factory=list)
    extraction_mode: ExtractionMode = ExtractionMode.PREVIEW
    source_paths: list[str] = Field(default_factory=list)
    source_processing: SourceProcessingConfig = Field(default_factory=SourceProcessingConfig)
    raw_cleaned_paths: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class InsightEvent(BaseModel):
    title: str
    description: str
    status: InsightStatus = InsightStatus.QUEUED
    meta: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class CharacterState(BaseModel):
    character: str
    summary: str = ""
    evidence_count: int = 0
    conflicts: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.now)


class ProjectPaths(BaseModel):
    root: Path
    raw: Path
    materials: Path
    cache: Path
    knowledge_base: Path
    output: Path
    config: Path
    facts: Path
    targeted_insights: Path
