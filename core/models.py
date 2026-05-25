from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExtractionMode(str, Enum):
    PREVIEW = "preview"
    FULL = "full"


class ExtractionArtifactStage(str, Enum):
    PREVIEW = "preview"
    FULL = "full"
    LEGACY_UNKNOWN = "legacy_unknown"


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


class CharacterCardKind(str, Enum):
    OFFICIAL = "official"
    PREVIEW = "preview"
    TEMPLATE = "template"


class CharacterCardStatus(str, Enum):
    EMPTY = "empty"
    DRAFT = "draft"
    PREVIEW = "preview"
    COMPILED = "compiled"
    STALE = "stale"
    FAILED = "failed"


class CharacterCardCompileSource(str, Enum):
    MANUAL = "manual"
    KNOWLEDGE_BASE = "knowledge_base"
    PREVIEW = "preview"
    IMPORTED_CHARAPICKER = "imported_charapicker"
    IMPORTED_EXTERNAL = "imported_external"


class CharacterCardCompileVariant(str, Enum):
    GENERAL = "general"
    ASTRBOT = "astrbot"
    CHARACTER_CARD_V2 = "character_card_v2"


class DialogueRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CharacterCardExportTarget(str, Enum):
    CHARAPICKER_JSON = "charapicker_json"
    CHARAPICKER_MARKDOWN = "charapicker_markdown"
    CHARAPICKER_HTML = "charapicker_html"
    CHARACTER_CARD_V2_JSON = "character_card_v2_json"
    ASTRBOT_COPY = "astrbot_copy"


class CharacterCardExportStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class SourceProcessingConfig(BaseModel):
    preset: SourceProcessingPreset = SourceProcessingPreset.ORIGINAL
    trim_enabled: bool = False
    trim_start: str = "00:00"
    trim_end: str = "00:00"
    transcode_enabled: bool = False
    codec: str = "H.264"
    encoder: str = ""
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
    include_previous_season_background: bool = True
    allow_provider_rejected_chunk_skip: bool = True
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


class CharacterCardIdentity(BaseModel):
    character_name: str = ""
    display_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    original_names: list[str] = Field(default_factory=list)
    romanized_names: list[str] = Field(default_factory=list)
    source_work: str = ""
    source_work_aliases: list[str] = Field(default_factory=list)
    role_titles: list[str] = Field(default_factory=list)
    species: str = ""
    gender: str = ""
    pronouns: str = ""
    age_text: str = ""
    visibility_label: str = ""


class CharacterCardCrop(BaseModel):
    source_width: int = 0
    source_height: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    scale: float = 1.0


class CharacterCardAssets(BaseModel):
    cover_path: str = ""
    cover_aspect_ratio: str = "9:16"
    original_cover_path: str = ""
    crop: CharacterCardCrop | None = None
    image_prompt: str = ""
    credits: str = ""
    external_assets: dict[str, Any] = Field(default_factory=dict)


class CharacterCardUserMetadata(BaseModel):
    notes: str = ""
    compile_requirements: str = ""
    compile_variant: CharacterCardCompileVariant = CharacterCardCompileVariant.GENERAL
    extra_dialogue_count: int | None = Field(default=None, ge=0, le=100)
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    folder: str = ""
    manual_reviewed: bool = False
    locked_fields: list[str] = Field(default_factory=list)
    creator: str = ""
    character_version: str = ""


class CharacterCardSourceContext(BaseModel):
    source_project_id: str = ""
    knowledge_base_ref: str = ""
    source_runs: list[str] = Field(default_factory=list)
    included_seasons: list[str] = Field(default_factory=list)
    included_episodes: list[str] = Field(default_factory=list)
    included_chunks: list[str] = Field(default_factory=list)
    excluded_materials: list[str] = Field(default_factory=list)
    compiler_version: str = "1"
    prompt_profile_id: str = ""
    model_profile_id: str = ""
    compiled_from_preview: bool = False
    imported_from_format: str = ""
    imported_card_id: str = ""
    imported_at: str = ""


class CharacterCardProfile(BaseModel):
    summary: str = ""
    long_description: str = ""
    appearance: str = ""
    personality: str = ""
    personality_traits: list[str] = Field(default_factory=list)
    values_and_beliefs: list[str] = Field(default_factory=list)
    goals_and_motivations: list[str] = Field(default_factory=list)
    fears_and_weaknesses: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    speech_style: list[str] = Field(default_factory=list)
    behavior_patterns: list[str] = Field(default_factory=list)
    emotional_range: list[str] = Field(default_factory=list)
    relationships_summary: str = ""
    backstory: str = ""
    current_state: str = ""
    growth_arc: str = ""
    scenario_default: str = ""
    world_context: str = ""
    canon_constraints: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


class CharacterCardPromptSurfaces(BaseModel):
    system_prompt: str = ""
    persona_prompt: str = ""
    scenario: str = ""
    first_message: str = ""
    alternate_greetings: list[str] = Field(default_factory=list)
    suggested_starters: list[str] = Field(default_factory=list)
    example_messages_text: str = ""
    post_history_instructions: str = ""
    author_note: str = ""
    creator_notes: str = ""
    custom_error_reply: str = ""
    markdown_card: str = ""
    html_card: str = ""


class CharacterCardDialogueMessage(BaseModel):
    role: DialogueRole = DialogueRole.USER
    content: str = ""


class CharacterCardDialogueExample(BaseModel):
    title: str = ""
    messages: list[CharacterCardDialogueMessage] = Field(default_factory=list)


class CharacterCardDialogue(BaseModel):
    first_message: str = ""
    alternate_greetings: list[str] = Field(default_factory=list)
    suggested_starters: list[str] = Field(default_factory=list)
    example_dialogues: list[CharacterCardDialogueExample] = Field(default_factory=list)
    preset_dialogues: list[CharacterCardDialogueExample] = Field(default_factory=list)


class CharacterCardBookEntry(BaseModel):
    keys: list[str] = Field(default_factory=list)
    content: str = ""
    enabled: bool = True
    insertion_order: int = 100


class CharacterCardBook(BaseModel):
    entries: list[CharacterCardBookEntry] = Field(default_factory=list)


class CharacterCardEvidence(BaseModel):
    evidence_count: int = 0
    refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class CharacterCardQuality(BaseModel):
    warnings: list[str] = Field(default_factory=list)
    needs_review: bool = False
    last_error: str = ""


class CharacterCardExportProfile(BaseModel):
    target: CharacterCardExportTarget
    generated_at: str = ""
    status: CharacterCardExportStatus = CharacterCardExportStatus.PENDING
    warnings: list[str] = Field(default_factory=list)
    output_path: str = ""
    field_mapping: dict[str, str] = Field(default_factory=dict)


class CharacterCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    format: str = "charapicker.card"
    schema_version: int = 1
    card_id: str = ""
    card_kind: CharacterCardKind = CharacterCardKind.OFFICIAL
    project_id: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    compiled_at: datetime | None = None
    revision: int = 1
    compile_status: CharacterCardStatus = CharacterCardStatus.EMPTY
    compile_source: CharacterCardCompileSource = CharacterCardCompileSource.MANUAL
    identity: CharacterCardIdentity = Field(default_factory=CharacterCardIdentity)
    assets: CharacterCardAssets = Field(default_factory=CharacterCardAssets)
    user_metadata: CharacterCardUserMetadata = Field(default_factory=CharacterCardUserMetadata)
    source_context: CharacterCardSourceContext = Field(default_factory=CharacterCardSourceContext)
    profile: CharacterCardProfile = Field(default_factory=CharacterCardProfile)
    prompt_surfaces: CharacterCardPromptSurfaces = Field(default_factory=CharacterCardPromptSurfaces)
    dialogue: CharacterCardDialogue = Field(default_factory=CharacterCardDialogue)
    character_book: CharacterCardBook = Field(default_factory=CharacterCardBook)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    evidence: CharacterCardEvidence = Field(default_factory=CharacterCardEvidence)
    quality: CharacterCardQuality = Field(default_factory=CharacterCardQuality)
    export_profiles: dict[str, CharacterCardExportProfile] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)


class CharacterCardSummary(BaseModel):
    card_id: str
    character_name: str = ""
    display_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    cover_path: str = ""
    compile_status: CharacterCardStatus = CharacterCardStatus.EMPTY
    compile_source: CharacterCardCompileSource = CharacterCardCompileSource.MANUAL
    compile_variant: CharacterCardCompileVariant = CharacterCardCompileVariant.GENERAL
    revision: int = 1
    updated_at: datetime = Field(default_factory=datetime.now)
    warnings: list[str] = Field(default_factory=list)


class CharacterCardCompileTarget(BaseModel):
    project_id: str
    card_id: str
    character_name: str
    compile_variant: CharacterCardCompileVariant = CharacterCardCompileVariant.GENERAL
    compile_source: CharacterCardCompileSource = CharacterCardCompileSource.KNOWLEDGE_BASE


class CharacterCardExportResult(BaseModel):
    target: CharacterCardExportTarget
    status: CharacterCardExportStatus = CharacterCardExportStatus.PENDING
    output_path: str = ""
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


class ChunkExtractionResult(BaseModel):
    season_id: str
    episode_id: str
    chunk_id: str
    extraction_stage: ExtractionArtifactStage = ExtractionArtifactStage.LEGACY_UNKNOWN
    run_type: str = ""
    source_path: str = ""
    source_kind: str = ""
    schema_version: int = 1
    targets: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    behavior_traits: list[str] = Field(default_factory=list)
    dialogue_style: list[str] = Field(default_factory=list)
    relationship_interactions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    character_state_changes: list[str] = Field(default_factory=list)
    insight_summary: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class TranscriptSource(BaseModel):
    material_path: str = ""
    material_paths: list[str] = Field(default_factory=list)
    material_time_ranges: list[dict[str, Any]] = Field(default_factory=list)
    source_fingerprint: str = ""
    season_id: str = ""
    episode_id: str = ""


class TranscriptMetadata(BaseModel):
    backend: str = "whisper.cpp"
    runtime_version: str = ""
    runtime_package: str = ""
    runtime_path: str = ""
    model_file: str = ""
    model_path: str = ""
    language: str = "auto"
    generated_at: datetime = Field(default_factory=datetime.now)
    cache_key: str = ""


class TranscriptSegment(BaseModel):
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    text: str = ""


class EpisodeTranscript(BaseModel):
    schema_version: int = 1
    source: TranscriptSource = Field(default_factory=TranscriptSource)
    transcription: TranscriptMetadata = Field(default_factory=TranscriptMetadata)
    segments: list[TranscriptSegment] = Field(default_factory=list)
    plain_text: str = ""


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
