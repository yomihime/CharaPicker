from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from utils.app_metadata import (
    APP_NAME,
    APP_RELEASE_STAGE,
    APP_VERSION,
    HTTP_USER_AGENT,
    format_version_tag,
)
from utils.global_store import get_global_value, set_global_value
from utils.network_middleware import (
    NetworkMiddlewareError,
    open_response,
    read_json,
    redact_sensitive_text,
)


LOGGER = logging.getLogger(__name__)

GITHUB_RELEASES_API_URL = "https://api.github.com/repos/yomihime/CharaPicker/releases?per_page=100"
UPDATE_PRERELEASES_KEY = "updates/include_prereleases"
UPDATE_ACK_ENV = "CHARAPICKER_UPDATE_ACK_PATH"
UPDATE_RUNNER_NAME = "CharaPickerUpdater.exe"
UPDATE_ARCHIVE_ROOT = APP_NAME
UPDATE_ASSET_SUFFIX = "windows-x64.zip"
PRESERVED_RUNTIME_PATHS = ("projects", "config.yaml", "log", "bin", "models")
MAX_UPDATE_ARCHIVE_MEMBERS = 100_000
MAX_UPDATE_EXTRACTED_BYTES = 8 * 1024 * 1024 * 1024
VERSION_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<stage>alpha|beta|rc)(?:\.(?P<stage_index>\d+))?)?$",
    re.IGNORECASE,
)
CHECKSUM_PATTERN = re.compile(r"^(?P<digest>[0-9a-fA-F]{64})(?:\s+\*?(?P<name>.+))?$")
STAGE_RANK = {"alpha": 0, "beta": 1, "rc": 2, "release": 3}

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class AppUpdateError(RuntimeError):
    pass


class UpdateCheckError(AppUpdateError):
    pass


class UpdatePackageUnavailableError(UpdateCheckError):
    def __init__(self, tag_name: str) -> None:
        super().__init__(tag_name)
        self.tag_name = tag_name


class UpdateDownloadError(AppUpdateError):
    pass


class UpdateDownloadCancelled(UpdateDownloadError):
    pass


class UpdateLaunchError(AppUpdateError):
    pass


@total_ordering
@dataclass(frozen=True, slots=True)
class AppVersion:
    major: int
    minor: int
    patch: int
    stage: str = "release"
    stage_index: int = 0

    @classmethod
    def parse(cls, value: str) -> AppVersion:
        match = VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ValueError(f"Unsupported version tag: {value}")
        stage = (match.group("stage") or "release").lower()
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            stage=stage,
            stage_index=int(match.group("stage_index") or 0),
        )

    @property
    def public_tag(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.stage == "release":
            return version
        suffix = self.stage
        if self.stage_index:
            suffix = f"{suffix}.{self.stage_index}"
        return f"{version}-{suffix}"

    @property
    def is_prerelease(self) -> bool:
        return self.stage != "release"

    def _comparison_key(self) -> tuple[int, int, int, int, int]:
        return (
            self.major,
            self.minor,
            self.patch,
            STAGE_RANK[self.stage],
            self.stage_index,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, AppVersion):
            return NotImplemented
        return self._comparison_key() < other._comparison_key()


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True, slots=True)
class UpdateRelease:
    tag_name: str
    version: AppVersion
    release_name: str
    release_url: str
    notes: str
    prerelease: bool
    archive: ReleaseAsset
    checksum: ReleaseAsset


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    version_tag: str
    workspace: Path
    payload_dir: Path
    updater_path: Path


def include_prereleases_preference() -> bool:
    return bool(get_global_value(UPDATE_PRERELEASES_KEY, False))


def set_include_prereleases_preference(enabled: bool) -> None:
    set_global_value(UPDATE_PRERELEASES_KEY, bool(enabled))


def current_app_version() -> AppVersion:
    return AppVersion.parse(format_version_tag(APP_VERSION, APP_RELEASE_STAGE))


def check_for_update(*, include_prereleases: bool) -> UpdateRelease | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": HTTP_USER_AGENT,
    }
    try:
        payload = read_json(GITHUB_RELEASES_API_URL, headers=headers, timeout=30)
    except (NetworkMiddlewareError, ValueError) as exc:
        raise UpdateCheckError(redact_sensitive_text(exc)) from exc
    if not isinstance(payload, list):
        raise UpdateCheckError("GitHub Releases returned an unexpected response.")

    current = current_app_version()
    candidates: list[tuple[AppVersion, dict[str, Any]]] = []
    for item in payload:
        if not isinstance(item, dict) or bool(item.get("draft")):
            continue
        tag_name = str(item.get("tag_name") or "").strip()
        try:
            version = AppVersion.parse(tag_name)
        except ValueError:
            LOGGER.warning("Ignoring release with unsupported tag; tag=%s", tag_name)
            continue
        is_prerelease = bool(item.get("prerelease")) or version.is_prerelease
        if is_prerelease and not include_prereleases:
            continue
        if version > current:
            candidates.append((version, item))

    if not candidates:
        return None

    version, release_payload = max(candidates, key=lambda candidate: candidate[0])
    release = _release_from_payload(version, release_payload)
    if release is None:
        tag_name = str(release_payload.get("tag_name") or version.public_tag)
        raise UpdatePackageUnavailableError(tag_name)
    return release


def prepare_update(
    release: UpdateRelease,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> PreparedUpdate:
    install_dir = packaged_install_dir()
    workspace = Path(
        tempfile.mkdtemp(
            prefix=f".{APP_NAME.lower()}-update-",
            dir=install_dir.parent,
        )
    )
    archive_path = workspace / release.archive.name
    checksum_path = workspace / release.checksum.name
    extract_dir = workspace / "payload"

    def emit(value: int, step: str) -> None:
        if progress:
            progress(value, step)

    try:
        emit(2, "preparing")
        _check_cancelled(cancelled)
        _download_file(
            release.checksum.download_url,
            checksum_path,
            progress=lambda ratio: emit(3 + int(ratio * 4), "checksum"),
            cancelled=cancelled,
        )
        expected_digest = _read_expected_checksum(checksum_path, release.archive.name)

        emit(8, "download")
        actual_digest = _download_file(
            release.archive.download_url,
            archive_path,
            progress=lambda ratio: emit(8 + int(ratio * 67), "download"),
            cancelled=cancelled,
            calculate_sha256=True,
        )
        emit(78, "verify")
        if actual_digest.lower() != expected_digest.lower():
            raise UpdateDownloadError("The downloaded update package failed SHA-256 verification.")

        emit(84, "extract")
        extract_dir.mkdir()
        _extract_update_archive(archive_path, extract_dir, cancelled=cancelled)
        payload_dir = extract_dir / UPDATE_ARCHIVE_ROOT
        if not (payload_dir / f"{APP_NAME}.exe").is_file():
            raise UpdateDownloadError(f"The update package does not contain {APP_NAME}.exe.")
        updater_path = payload_dir / UPDATE_RUNNER_NAME
        if not updater_path.is_file():
            raise UpdateDownloadError(f"The update package does not contain {UPDATE_RUNNER_NAME}.")
        emit(100, "ready")
        return PreparedUpdate(
            version_tag=release.version.public_tag,
            workspace=workspace,
            payload_dir=payload_dir,
            updater_path=updater_path,
        )
    except UpdateDownloadCancelled:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    except (OSError, NetworkMiddlewareError, zipfile.BadZipFile, UpdateDownloadError) as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        if isinstance(exc, UpdateDownloadError):
            raise
        raise UpdateDownloadError(redact_sensitive_text(exc)) from exc


def packaged_install_dir() -> Path:
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        raise UpdateDownloadError("Automatic updates are only supported by packaged Windows builds.")
    install_dir = Path(sys.executable).resolve().parent
    if not (install_dir / f"{APP_NAME}.exe").is_file():
        raise UpdateDownloadError("The application installation directory could not be verified.")
    return install_dir


def launch_prepared_update(
    prepared: PreparedUpdate,
    *,
    current_pid: int,
    failure_title: str,
    failure_message: str,
) -> None:
    install_dir = packaged_install_dir()
    token = uuid.uuid4().hex
    backup_dir = install_dir.parent / f".{APP_NAME.lower()}-backup-{token}"
    ack_path = prepared.workspace / "startup-ack"
    request_path = prepared.workspace / "update-request.json"
    updater_copy = Path(tempfile.gettempdir()) / f"{APP_NAME}Updater-{token}.exe"
    log_path = Path(tempfile.gettempdir()) / f"{APP_NAME}Updater-{token}.log"

    request = {
        "schema_version": 1,
        "current_pid": current_pid,
        "install_dir": str(install_dir),
        "payload_dir": str(prepared.payload_dir),
        "workspace": str(prepared.workspace),
        "backup_dir": str(backup_dir),
        "ack_path": str(ack_path),
        "log_path": str(log_path),
        "executable_name": f"{APP_NAME}.exe",
        "relaunch_cwd": str(Path.cwd().resolve()),
        "preserve": list(PRESERVED_RUNTIME_PATHS),
        "failure_title": failure_title,
        "failure_message": failure_message,
    }
    try:
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copy2(prepared.updater_path, updater_copy)
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [str(updater_copy), "--request", str(request_path)],
            cwd=tempfile.gettempdir(),
            close_fds=True,
            creationflags=creation_flags,
        )
    except (OSError, ValueError) as exc:
        updater_copy.unlink(missing_ok=True)
        raise UpdateLaunchError(redact_sensitive_text(exc)) from exc


def discard_prepared_update(prepared: PreparedUpdate) -> None:
    shutil.rmtree(prepared.workspace, ignore_errors=True)


def acknowledge_update_startup() -> None:
    raw_path = os.environ.pop(UPDATE_ACK_ENV, "").strip()
    if not raw_path:
        return
    try:
        Path(raw_path).write_text("ok\n", encoding="ascii")
    except OSError:
        LOGGER.warning("Failed to acknowledge updated application startup", exc_info=True)


def _release_from_payload(
    version: AppVersion,
    payload: dict[str, Any],
) -> UpdateRelease | None:
    archive_name = f"{APP_NAME}-v{version.public_tag}-{UPDATE_ASSET_SUFFIX}"
    checksum_name = f"{archive_name}.sha256"
    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, list):
        return None
    assets: dict[str, ReleaseAsset] = {}
    for raw_asset in assets_payload:
        if not isinstance(raw_asset, dict):
            continue
        name = str(raw_asset.get("name") or "").strip()
        download_url = str(raw_asset.get("browser_download_url") or "").strip()
        if name not in {archive_name, checksum_name} or not _is_https_url(download_url):
            continue
        assets[name] = ReleaseAsset(
            name=name,
            download_url=download_url,
            size=max(0, int(raw_asset.get("size") or 0)),
        )
    if archive_name not in assets or checksum_name not in assets:
        return None
    return UpdateRelease(
        tag_name=str(payload.get("tag_name") or f"v{version.public_tag}"),
        version=version,
        release_name=str(payload.get("name") or payload.get("tag_name") or version.public_tag),
        release_url=str(payload.get("html_url") or ""),
        notes=str(payload.get("body") or ""),
        prerelease=bool(payload.get("prerelease")) or version.is_prerelease,
        archive=assets[archive_name],
        checksum=assets[checksum_name],
    )


def _is_https_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.lower() == "https" and bool(parsed.netloc)


def _check_cancelled(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise UpdateDownloadCancelled("Update download cancelled.")


def _download_file(
    url: str,
    destination: Path,
    *,
    progress: Callable[[float], None] | None = None,
    cancelled: CancelCallback | None = None,
    calculate_sha256: bool = False,
) -> str:
    digest = hashlib.sha256()
    headers = {"User-Agent": HTTP_USER_AGENT}
    with open_response("GET", url, headers=headers, timeout=60, stream=True) as response:
        if response.status_code >= 400:
            raise UpdateDownloadError(f"HTTP {response.status_code}")
        total_size = max(0, int(response.headers.get("Content-Length") or 0))
        downloaded = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                _check_cancelled(cancelled)
                if not chunk:
                    continue
                output.write(chunk)
                if calculate_sha256:
                    digest.update(chunk)
                downloaded += len(chunk)
                if progress and total_size:
                    progress(min(1.0, downloaded / total_size))
    if progress:
        progress(1.0)
    return digest.hexdigest() if calculate_sha256 else ""


def _read_expected_checksum(path: Path, expected_name: str) -> str:
    try:
        first_line = path.read_text(encoding="ascii").splitlines()[0].strip()
    except (OSError, UnicodeError, IndexError) as exc:
        raise UpdateDownloadError("The update checksum file is invalid.") from exc
    match = CHECKSUM_PATTERN.fullmatch(first_line)
    if match is None:
        raise UpdateDownloadError("The update checksum file is invalid.")
    checksum_name = (match.group("name") or "").strip()
    if checksum_name and checksum_name != expected_name:
        raise UpdateDownloadError("The update checksum does not match the package name.")
    return match.group("digest").lower()


def _extract_update_archive(
    archive_path: Path,
    extract_dir: Path,
    *,
    cancelled: CancelCallback | None = None,
) -> None:
    extract_root = extract_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not members:
            raise UpdateDownloadError("The update package is empty.")
        if len(members) > MAX_UPDATE_ARCHIVE_MEMBERS:
            raise UpdateDownloadError("The update package contains too many files.")
        if sum(member.file_size for member in members) > MAX_UPDATE_EXTRACTED_BYTES:
            raise UpdateDownloadError("The extracted update package is too large.")
        for member in members:
            _check_cancelled(cancelled)
            member_path = PurePosixPath(member.filename.replace("\\", "/"))
            if (
                member_path.is_absolute()
                or not member_path.parts
                or member_path.parts[0] != UPDATE_ARCHIVE_ROOT
                or ".." in member_path.parts
            ):
                raise UpdateDownloadError("The update package contains unsafe paths.")
            unix_mode = member.external_attr >> 16
            if (unix_mode & 0o170000) == 0o120000:
                raise UpdateDownloadError("The update package contains unsupported symbolic links.")
            target = (extract_dir / Path(*member_path.parts)).resolve()
            if not target.is_relative_to(extract_root):
                raise UpdateDownloadError("The update package contains unsafe paths.")
        for member in members:
            _check_cancelled(cancelled)
            archive.extract(member, extract_dir)
