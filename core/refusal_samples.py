from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from utils.app_metadata import APP_VERSION_TAG
from utils.network_middleware import redact_sensitive_text
from utils.paths import ensure_project_tree, project_paths


REFUSAL_SAMPLE_SCHEMA_VERSION = 1
REFUSAL_SAMPLE_HASH_SALT_ID = "CharaPickerRefusalSample:v1"
REFUSAL_SAMPLE_HASH_ALGORITHM = "sha256-16"
REFUSAL_SAMPLE_FILE_NAME = "refusal_sample.json"
PACKAGE_MANIFEST_FILE_NAME = "package_manifest.json"
DEFAULT_MAX_MATERIAL_COPY_BYTES = 5 * 1024 * 1024

MaterialCopyPolicy = Literal[
    "copy_allowed",
    "index_only_large",
    "missing",
    "unsafe_path",
    "outside_project",
]


class RefusalSampleSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = ""
    project_relative_path: str = ""
    media_type: str = ""
    content_form: str = ""
    material_id: str = ""
    size_bytes: int | None = None
    copy_policy: MaterialCopyPolicy = "missing"


class ExtractionFailureSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str = ""
    prompt_purpose: str = ""
    provider: str = ""
    backend: str = ""
    model_name: str = ""
    model_profile_id: str = ""
    media_type: str = ""
    content_form: str = ""
    unit_id: str = ""
    unit_kind: str = ""
    material_id: str = ""
    source_path: str = ""
    source_paths: list[str] = Field(default_factory=list)
    extraction_stage: str = ""
    extraction_run_id: str = ""
    season_id: str = ""
    episode_id: str = ""
    chunk_id: str = ""
    failure_kind: str = ""
    error_type: str = ""
    error_summary: str = ""
    user_prompt_override_present: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefusalSampleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = REFUSAL_SAMPLE_SCHEMA_VERSION
    sample_id: str
    created_at: str
    project_id: str
    project_name: str = ""
    prompt_purpose: str = ""
    provider: str = ""
    backend: str = ""
    model_name: str = ""
    model_profile_id: str = ""
    media_type: str = ""
    content_form: str = ""
    unit_id: str = ""
    unit_kind: str = ""
    material_id: str = ""
    source_path: str = ""
    source_refs: list[RefusalSampleSourceRef] = Field(default_factory=list)
    extraction_stage: str = ""
    extraction_run_id: str = ""
    season_id: str = ""
    episode_id: str = ""
    chunk_id: str = ""
    failure_kind: str = ""
    error_type: str = ""
    error_summary: str = ""
    user_prompt_override_present: bool = False
    app_version: str = APP_VERSION_TAG
    privacy_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sample_hash: str = ""
    hash_algorithm: str = REFUSAL_SAMPLE_HASH_ALGORITHM
    hash_salt_id: str = REFUSAL_SAMPLE_HASH_SALT_ID


class RefusalSampleWriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    sample_dir: str
    sample_path: str
    sample_hash: str


class RefusalSamplePackageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    zip_path: str
    copied_materials: list[str] = Field(default_factory=list)
    indexed_materials: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def record_extraction_failure_sample(
    request: ExtractionFailureSampleRequest,
    *,
    max_material_copy_bytes: int = DEFAULT_MAX_MATERIAL_COPY_BYTES,
) -> RefusalSampleWriteResult:
    paths = ensure_project_tree(request.project_id)
    created_at = _utc_timestamp()
    sample_id = f"sample-{uuid4().hex[:12]}"
    source_refs = _build_source_refs(
        request,
        max_material_copy_bytes=max_material_copy_bytes,
    )
    record = RefusalSampleRecord(
        sample_id=sample_id,
        created_at=created_at,
        project_id=request.project_id,
        project_name=request.project_name or _project_name(request.project_id),
        prompt_purpose=_clean_text(request.prompt_purpose, 120),
        provider=_clean_text(request.provider, 80),
        backend=_clean_text(request.backend, 80),
        model_name=_clean_text(request.model_name, 120),
        model_profile_id=_clean_text(request.model_profile_id, 120),
        media_type=_clean_text(request.media_type, 40),
        content_form=_clean_text(request.content_form, 80),
        unit_id=_clean_text(request.unit_id, 120),
        unit_kind=_clean_text(request.unit_kind, 80),
        material_id=_clean_text(request.material_id, 120),
        source_path=_clean_text(_safe_display_source_path(request.source_path), 300),
        source_refs=source_refs,
        extraction_stage=_clean_text(request.extraction_stage, 80),
        extraction_run_id=_clean_text(request.extraction_run_id, 120),
        season_id=_clean_text(request.season_id, 120),
        episode_id=_clean_text(request.episode_id, 120),
        chunk_id=_clean_text(request.chunk_id, 120),
        failure_kind=_clean_text(request.failure_kind, 120),
        error_type=_clean_text(request.error_type, 120),
        error_summary=_clean_text(request.error_summary, 500),
        user_prompt_override_present=request.user_prompt_override_present,
        privacy_notes=[
            "API keys, full prompts, full model responses, and raw private text are not stored.",
            "Source paths are project-relative when possible; outside-project paths are redacted.",
        ],
        metadata=_safe_metadata(request.metadata),
    )
    record.sample_hash = _record_hash(record)
    sample_dir = paths.cache / "refusal_samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_path = sample_dir / REFUSAL_SAMPLE_FILE_NAME
    sample_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return RefusalSampleWriteResult(
        sample_id=sample_id,
        sample_dir=str(sample_dir),
        sample_path=str(sample_path),
        sample_hash=record.sample_hash,
    )


def load_refusal_sample(project_id: str, sample_id: str) -> RefusalSampleRecord:
    sample_path = _sample_path(project_id, sample_id)
    return RefusalSampleRecord.model_validate(json.loads(sample_path.read_text(encoding="utf-8")))


def package_refusal_sample(
    project_id: str,
    sample_id: str,
    *,
    include_materials: bool,
    max_material_copy_bytes: int = DEFAULT_MAX_MATERIAL_COPY_BYTES,
) -> RefusalSamplePackageResult:
    paths = ensure_project_tree(project_id)
    record = load_refusal_sample(project_id, sample_id)
    output_dir = paths.output / "refusal_samples"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / _zip_file_name(record)
    copied: list[str] = []
    indexed: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(_sample_path(project_id, sample_id), REFUSAL_SAMPLE_FILE_NAME)
        for source_ref in record.source_refs:
            material_path = _source_ref_path(paths.root, source_ref)
            label = source_ref.project_relative_path or source_ref.source_path
            if source_ref.copy_policy == "missing":
                missing.append(label)
                continue
            if source_ref.copy_policy not in {"copy_allowed", "index_only_large"}:
                indexed.append(label)
                warnings.append(f"material not copied due to {source_ref.copy_policy}: {label}")
                continue
            if not include_materials:
                indexed.append(label)
                continue
            if material_path is None or not material_path.is_file():
                missing.append(label)
                continue
            size_bytes = material_path.stat().st_size
            if size_bytes > max_material_copy_bytes:
                indexed.append(label)
                warnings.append(f"material exceeds copy limit and was indexed only: {label}")
                continue
            archive_name = f"materials/{_archive_safe_name(_material_archive_label(label))}"
            archive.write(material_path, archive_name)
            copied.append(archive_name)

        manifest = {
            "schema_version": 1,
            "sample_id": sample_id,
            "sample_hash": record.sample_hash,
            "include_materials": include_materials,
            "max_material_copy_bytes": max_material_copy_bytes,
            "copied_materials": copied,
            "indexed_materials": indexed,
            "missing_materials": missing,
            "warnings": warnings,
        }
        archive.writestr(
            PACKAGE_MANIFEST_FILE_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    return RefusalSamplePackageResult(
        sample_id=sample_id,
        zip_path=str(zip_path),
        copied_materials=copied,
        indexed_materials=indexed,
        missing_materials=missing,
        warnings=warnings,
    )


def _build_source_refs(
    request: ExtractionFailureSampleRequest,
    *,
    max_material_copy_bytes: int,
) -> list[RefusalSampleSourceRef]:
    refs: list[RefusalSampleSourceRef] = []
    seen: set[str] = set()
    for source_path in [request.source_path, *request.source_paths]:
        source_path = str(source_path).strip()
        if not source_path or source_path in seen:
            continue
        seen.add(source_path)
        refs.append(
            _source_ref(
                request.project_id,
                source_path,
                media_type=request.media_type,
                content_form=request.content_form,
                material_id=request.material_id,
                max_material_copy_bytes=max_material_copy_bytes,
            )
        )
    return refs


def _source_ref(
    project_id: str,
    source_path: str,
    *,
    media_type: str,
    content_form: str,
    material_id: str,
    max_material_copy_bytes: int,
) -> RefusalSampleSourceRef:
    paths = project_paths(project_id)
    project_root = paths.root.resolve()
    candidate = _candidate_source_path(paths.root, paths.materials, source_path)
    if candidate is None:
        return RefusalSampleSourceRef(
            source_path=_safe_display_source_path(source_path),
            media_type=_clean_text(media_type, 40),
            content_form=_clean_text(content_form, 80),
            material_id=_clean_text(material_id, 120),
            copy_policy="outside_project",
        )
    resolved = candidate.resolve(strict=False)
    if not _is_relative_to(resolved, project_root):
        policy: MaterialCopyPolicy = "outside_project" if Path(source_path).is_absolute() else "unsafe_path"
        return RefusalSampleSourceRef(
            source_path=_safe_display_source_path(source_path),
            media_type=_clean_text(media_type, 40),
            content_form=_clean_text(content_form, 80),
            material_id=_clean_text(material_id, 120),
            copy_policy=policy,
        )
    project_relative_path = resolved.relative_to(project_root).as_posix()
    if not resolved.is_file():
        policy: MaterialCopyPolicy = "missing"
        size_bytes = None
    else:
        size_bytes = resolved.stat().st_size
        policy = "copy_allowed" if size_bytes <= max_material_copy_bytes else "index_only_large"
    return RefusalSampleSourceRef(
        source_path=_clean_text(_safe_display_source_path(source_path), 300),
        project_relative_path=project_relative_path,
        media_type=_clean_text(media_type, 40),
        content_form=_clean_text(content_form, 80),
        material_id=_clean_text(material_id, 120),
        size_bytes=size_bytes,
        copy_policy=policy,
    )


def _candidate_source_path(project_root: Path, materials_root: Path, source_path: str) -> Path | None:
    candidate = Path(source_path)
    if candidate.is_absolute():
        return candidate
    parts = candidate.parts
    if parts and parts[0] in {"raw", "materials", "cache", "knowledge_base", "output"}:
        return project_root / candidate
    if ".." in parts:
        return None
    return materials_root / candidate


def _source_ref_path(project_root: Path, source_ref: RefusalSampleSourceRef) -> Path | None:
    if not source_ref.project_relative_path:
        return None
    candidate = (project_root / source_ref.project_relative_path).resolve(strict=False)
    project_root = project_root.resolve()
    if not _is_relative_to(candidate, project_root):
        return None
    return candidate


def _sample_path(project_id: str, sample_id: str) -> Path:
    return project_paths(project_id).cache / "refusal_samples" / sample_id / REFUSAL_SAMPLE_FILE_NAME


def _zip_file_name(record: RefusalSampleRecord) -> str:
    project_name = _slug(record.project_name or record.project_id)
    timestamp = _compact_timestamp(record.created_at)
    return f"{project_name}_{timestamp}_{record.sample_hash}.zip"


def _record_hash(record: RefusalSampleRecord) -> str:
    payload = record.model_dump(
        mode="json",
        exclude={"sample_hash", "hash_algorithm", "hash_salt_id"},
    )
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = sha256(f"{REFUSAL_SAMPLE_HASH_SALT_ID}:{canonical}".encode("utf-8")).hexdigest()
    return digest[:16]


def _project_name(project_id: str) -> str:
    config_path = project_paths(project_id).config
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return project_id
    name = str(payload.get("name", "")).strip()
    return name or project_id


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        if _looks_sensitive_key(key_text):
            output[key_text] = "<redacted>"
        elif isinstance(item, (str, int, float, bool)) or item is None:
            output[key_text] = _clean_text(item, 300) if isinstance(item, str) else item
        elif isinstance(item, list):
            output[key_text] = [_clean_text(entry, 160) for entry in item[:20]]
        elif isinstance(item, dict):
            output[key_text] = {
                str(sub_key): _clean_text(sub_value, 160)
                for sub_key, sub_value in list(item.items())[:20]
                if not _looks_sensitive_key(str(sub_key))
            }
    return output


def _clean_text(value: object, max_length: int) -> str:
    text = " ".join(redact_sensitive_text(value).split())
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _safe_display_source_path(source_path: str) -> str:
    path = Path(source_path)
    if path.is_absolute():
        return f"<outside_project>/{path.name}"
    return str(path).replace("\\", "/")


def _looks_sensitive_key(key: str) -> bool:
    return any(part in key.casefold() for part in ("api_key", "apikey", "token", "secret", "password"))


def _archive_safe_name(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts) or "material"


def _material_archive_label(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    for prefix in ("materials/", "raw/"):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def _slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._-")
    return slug or "project"


def _compact_timestamp(value: str) -> str:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return re.sub(r"[^0-9A-Za-z]+", "", text)[:15] or "unknown_time"
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
