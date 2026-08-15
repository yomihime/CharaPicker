from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, model_validator

from utils.download_integrity import SHA256_PATTERN
from utils.paths import APP_ROOT


RUNTIME_DOWNLOADS_PATH = APP_ROOT / "res" / "runtime_downloads.json"
TRUSTED_RUNTIME_DOWNLOAD_HOSTS = {"github.com", "huggingface.co", "www.gyan.dev"}
MAX_RUNTIME_ASSET_BYTES = 2 * 1024 * 1024 * 1024


class RuntimeDownloadManifestError(RuntimeError):
    pass


class RuntimeDownloadAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    file_name: str
    url: str
    sha256: str
    size_bytes: int
    max_bytes: int
    source_revision: str

    @model_validator(mode="after")
    def validate_trust_boundary(self) -> RuntimeDownloadAsset:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname not in TRUSTED_RUNTIME_DOWNLOAD_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("runtime asset URL is outside the trusted HTTPS origins")
        if PurePosixPath(parsed.path).name != self.file_name:
            raise ValueError("runtime asset filename does not match its URL")
        if any(segment.casefold() in {"latest", "main"} for segment in parsed.path.split("/")):
            raise ValueError("runtime asset URL must pin a reviewed version or revision")
        if SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("runtime asset SHA-256 is invalid")
        if not self.version.strip() or not self.source_revision.strip():
            raise ValueError("runtime asset version and source revision are required")
        if self.size_bytes <= 0 or self.max_bytes < self.size_bytes:
            raise ValueError("runtime asset size policy is invalid")
        if self.max_bytes > MAX_RUNTIME_ASSET_BYTES:
            raise ValueError("runtime asset size limit exceeds the application maximum")
        return self


class RuntimeDownloadManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    assets: dict[str, RuntimeDownloadAsset]

    @model_validator(mode="after")
    def validate_manifest(self) -> RuntimeDownloadManifest:
        if self.schema_version != 1:
            raise ValueError("unsupported runtime download manifest schema")
        if not self.assets:
            raise ValueError("runtime download manifest contains no assets")
        return self


def load_runtime_download_manifest(
    path: Path = RUNTIME_DOWNLOADS_PATH,
) -> RuntimeDownloadManifest:
    candidates = _manifest_candidates(path)
    resolved_path = next((candidate for candidate in candidates if candidate.is_file()), path)
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        return RuntimeDownloadManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeDownloadManifestError(
            f"Runtime download manifest is invalid: {resolved_path}"
        ) from exc


def runtime_download_asset(asset_id: str) -> RuntimeDownloadAsset:
    manifest = load_runtime_download_manifest()
    try:
        return manifest.assets[asset_id]
    except KeyError as exc:
        raise RuntimeDownloadManifestError(f"Unknown runtime download asset: {asset_id}") from exc


def _manifest_candidates(primary_path: Path) -> list[Path]:
    candidates = [primary_path]
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.append(executable_dir / "res" / "runtime_downloads.json")
        candidates.append(executable_dir / "_internal" / "res" / "runtime_downloads.json")
    return candidates
