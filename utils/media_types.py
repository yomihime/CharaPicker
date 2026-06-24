"""Shared source media suffixes and extraction support metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Literal


MediaTypeName = Literal["video", "image", "audio", "text"]
ContentFormHint = Literal["unknown", "script", "image_set", "mixed"]


class SourceSupportLevel(str, Enum):
    SUPPORTED = "supported"
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SourceSupportProfile:
    media_type: MediaTypeName | None
    content_form_hint: ContentFormHint
    import_supported: bool
    preview_support: SourceSupportLevel
    formal_support: SourceSupportLevel
    reason: str = ""


@dataclass(frozen=True)
class SourceCollectionProfile:
    media_types: tuple[MediaTypeName, ...]
    content_form_hint: ContentFormHint
    unsupported_paths: tuple[Path, ...]


VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mkv",
        ".mov",
        ".avi",
        ".webm",
        ".flv",
        ".wmv",
        ".m4v",
    }
)
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
SUPPORTED_STATIC_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"})
SUPPORTED_TIMED_TEXT_SUFFIXES = frozenset({".srt", ".ass"})
DEFERRED_TIMED_TEXT_SUFFIXES = frozenset({".vtt", ".lrc"})
TIMED_TEXT_SUFFIXES = SUPPORTED_TIMED_TEXT_SUFFIXES | DEFERRED_TIMED_TEXT_SUFFIXES
TEXT_SUFFIXES = frozenset({".txt", ".md", ".json"}) | TIMED_TEXT_SUFFIXES
COMIC_ARCHIVE_SUFFIXES = frozenset({".cbz", ".cbr", ".zip", ".rar", ".7z"})
SUPPORTED_SOURCE_SUFFIXES = VIDEO_SUFFIXES | IMAGE_SUFFIXES | AUDIO_SUFFIXES | TEXT_SUFFIXES


_VIDEO_PROFILE = SourceSupportProfile(
    media_type="video",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.SUPPORTED,
    formal_support=SourceSupportLevel.SUPPORTED,
)
_IMAGE_PROFILE = SourceSupportProfile(
    media_type="image",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.SUPPORTED,
    formal_support=SourceSupportLevel.SUPPORTED,
)
_GIF_PROFILE = SourceSupportProfile(
    media_type="image",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="animated_image_not_supported",
)
_BMP_PROFILE = SourceSupportProfile(
    media_type="image",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="bmp_image_not_supported",
)
_AUDIO_PROFILE = SourceSupportProfile(
    media_type="audio",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.SUPPORTED,
    formal_support=SourceSupportLevel.SUPPORTED,
    reason="transcript_required",
)
_TEXT_PROFILE = SourceSupportProfile(
    media_type="text",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.PLANNED,
    formal_support=SourceSupportLevel.PLANNED,
)
_TIMED_TEXT_PROFILE = SourceSupportProfile(
    media_type="text",
    content_form_hint="script",
    import_supported=True,
    preview_support=SourceSupportLevel.SUPPORTED,
    formal_support=SourceSupportLevel.SUPPORTED,
)
_VTT_PROFILE = SourceSupportProfile(
    media_type="text",
    content_form_hint="script",
    import_supported=True,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="vtt_timed_text_not_supported",
)
_LRC_PROFILE = SourceSupportProfile(
    media_type="text",
    content_form_hint="script",
    import_supported=True,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="lrc_timed_text_not_supported",
)
_CONTROLLED_JSON_PROFILE = SourceSupportProfile(
    media_type="text",
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.PLANNED,
    formal_support=SourceSupportLevel.PLANNED,
    reason="controlled_json_only",
)
_EXTENSIONLESS_PROFILE = SourceSupportProfile(
    media_type=None,
    content_form_hint="unknown",
    import_supported=True,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="extensionless_source_unclassified",
)
_COMIC_ARCHIVE_PROFILE = SourceSupportProfile(
    media_type=None,
    content_form_hint="unknown",
    import_supported=False,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="comic_archive_not_supported",
)
_UNKNOWN_PROFILE = SourceSupportProfile(
    media_type=None,
    content_form_hint="unknown",
    import_supported=False,
    preview_support=SourceSupportLevel.UNSUPPORTED,
    formal_support=SourceSupportLevel.UNSUPPORTED,
    reason="unknown_source_suffix",
)


def source_support_profile(path_or_suffix: str | Path) -> SourceSupportProfile:
    suffix = _normalized_suffix(path_or_suffix)
    if not suffix:
        return _EXTENSIONLESS_PROFILE
    if suffix in VIDEO_SUFFIXES:
        return _VIDEO_PROFILE
    if suffix == ".gif":
        return _GIF_PROFILE
    if suffix == ".bmp":
        return _BMP_PROFILE
    if suffix in IMAGE_SUFFIXES:
        return _IMAGE_PROFILE
    if suffix in AUDIO_SUFFIXES:
        return _AUDIO_PROFILE
    if suffix in SUPPORTED_TIMED_TEXT_SUFFIXES:
        return _TIMED_TEXT_PROFILE
    if suffix == ".vtt":
        return _VTT_PROFILE
    if suffix == ".lrc":
        return _LRC_PROFILE
    if suffix == ".json":
        return _CONTROLLED_JSON_PROFILE
    if suffix in TEXT_SUFFIXES:
        return _TEXT_PROFILE
    if suffix in COMIC_ARCHIVE_SUFFIXES:
        return _COMIC_ARCHIVE_PROFILE
    return _UNKNOWN_PROFILE


def source_media_type(path_or_suffix: str | Path) -> MediaTypeName | None:
    return source_support_profile(path_or_suffix).media_type


def is_import_supported_source(path: str | Path) -> bool:
    return source_support_profile(path).import_supported


def classify_source_collection(paths: Iterable[str | Path]) -> SourceCollectionProfile:
    material_paths = tuple(Path(path) for path in paths)
    profiles = tuple(source_support_profile(path) for path in material_paths)
    media_types = tuple(
        media_type
        for media_type in ("video", "image", "audio", "text")
        if any(profile.media_type == media_type for profile in profiles)
    )
    unsupported_paths = tuple(
        path for path, profile in zip(material_paths, profiles) if not profile.import_supported
    )

    if len(media_types) > 1:
        content_form_hint: ContentFormHint = "mixed"
    elif media_types == ("image",) and len(material_paths) > 1:
        content_form_hint = "image_set"
    elif media_types == ("text",) and profiles and all(
        profile.content_form_hint == "script" for profile in profiles
    ):
        content_form_hint = "script"
    else:
        content_form_hint = "unknown"

    return SourceCollectionProfile(
        media_types=media_types,
        content_form_hint=content_form_hint,
        unsupported_paths=unsupported_paths,
    )


def _normalized_suffix(path_or_suffix: str | Path) -> str:
    value = str(path_or_suffix).strip().lower()
    if not value:
        return ""
    if value.startswith(".") and "/" not in value and "\\" not in value:
        return value
    return Path(value).suffix.lower()
