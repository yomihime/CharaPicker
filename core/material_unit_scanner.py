from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from typing import Any

from core.extraction_plan import (
    ContentForm,
    EpisodePlan,
    ExtractionUnit,
    MaterialOrigin,
    MaterialRef,
    MediaType,
    PageRange,
    TextRange,
)
from utils.media_types import (
    IMAGE_SUFFIXES,
    SUPPORTED_TIMED_TEXT_SUFFIXES,
    TIMED_TEXT_SUFFIXES,
    classify_source_collection,
    source_media_type,
    source_support_profile,
)


FORMAL_MATERIAL_SCAN_TYPE = "formal_materials"
GENERIC_MATERIAL_SEASON_ID = "season_materials"


def extend_episode_plans(materials_root: Path, episodes: list[EpisodePlan]) -> list[EpisodePlan]:
    material_paths = _supported_non_video_material_paths(materials_root)
    timed_text_associations = _timed_text_associations(materials_root, episodes, material_paths)
    associated_paths = {path for paths in timed_text_associations.values() for path in paths}
    video_episodes = [
        _attach_timed_text_units(
            materials_root,
            episode,
            timed_text_associations.get((episode.season_id, episode.episode_id), []),
        )
        for episode in episodes
    ]
    standalone_episodes = _standalone_material_episodes(
        materials_root,
        [path for path in material_paths if path not in associated_paths],
    )
    return [*video_episodes, *standalone_episodes]


def _supported_non_video_material_paths(materials_root: Path) -> list[Path]:
    if not materials_root.exists():
        return []
    paths: list[Path] = []
    for path in materials_root.rglob("*"):
        media_type = source_media_type(path)
        if path.is_file() and media_type is not None and media_type != MediaType.VIDEO.value:
            paths.append(path)
    return sorted(paths, key=lambda path: _relative_material_path(materials_root, path).lower())


def _timed_text_associations(
    materials_root: Path,
    episodes: list[EpisodePlan],
    material_paths: list[Path],
) -> dict[tuple[str, str], list[Path]]:
    associations: dict[tuple[str, str], list[Path]] = {}
    for path in material_paths:
        if path.suffix.lower() not in TIMED_TEXT_SUFFIXES:
            continue
        matches = [
            episode
            for episode in episodes
            if _timed_text_matches_video_episode(materials_root, path, episode)
        ]
        if len(matches) != 1:
            continue
        match = matches[0]
        associations.setdefault((match.season_id, match.episode_id), []).append(path)
    return associations


def _attach_timed_text_units(
    materials_root: Path,
    episode: EpisodePlan,
    candidates: list[Path],
) -> EpisodePlan:
    candidates = sorted(
        candidates,
        key=lambda path: _relative_material_path(materials_root, path).lower(),
    )
    if not candidates:
        return episode

    added_units = [
        _material_unit(
            materials_root,
            path,
            season_id=episode.season_id,
            episode_id=episode.episode_id,
            content_form=ContentForm.SCRIPT,
            unit_kind=_text_unit_kind(path),
            metadata={"associated_video_episode": True},
        )
        for path in candidates
    ]
    content_forms = list(episode.content_forms)
    if ContentForm.SCRIPT not in content_forms:
        content_forms.append(ContentForm.SCRIPT)
    return episode.model_copy(
        update={
            "content_forms": content_forms,
            "units": [*episode.units, *added_units],
            "metadata": {
                **episode.metadata,
                "associated_timed_text_count": len(added_units),
            },
        }
    )


def _timed_text_matches_video_episode(
    materials_root: Path,
    timed_text_path: Path,
    episode: EpisodePlan,
) -> bool:
    relative_path = Path(_relative_material_path(materials_root, timed_text_path))
    legacy_source_path = _string(episode.metadata.get("legacy_source_path"))
    if legacy_source_path and relative_path.parent.as_posix() == legacy_source_path:
        return True

    video_paths = [
        Path(unit.material_ref.relative_path)
        for unit in episode.units
        if unit.media_type == MediaType.VIDEO
    ]
    return any(
        video_path.parent == relative_path.parent
        and video_path.stem.lower() == relative_path.stem.lower()
        for video_path in video_paths
    )


def _standalone_material_episodes(
    materials_root: Path,
    material_paths: list[Path],
) -> list[EpisodePlan]:
    image_paths = [path for path in material_paths if path.suffix.lower() in IMAGE_SUFFIXES]
    other_paths = [path for path in material_paths if path not in image_paths]
    episodes = [
        _image_collection_episode(materials_root, parent, paths)
        for parent, paths in _group_paths_by_parent(image_paths)
    ]
    episodes.extend(_single_material_episode(materials_root, path) for path in other_paths)
    return sorted(episodes, key=lambda episode: episode.sort_key)


def _group_paths_by_parent(paths: list[Path]) -> list[tuple[Path, list[Path]]]:
    groups: dict[Path, list[Path]] = {}
    for path in paths:
        groups.setdefault(path.parent, []).append(path)
    return [
        (parent, sorted(group_paths, key=lambda path: path.name.lower()))
        for parent, group_paths in sorted(groups.items(), key=lambda item: item[0].as_posix().lower())
    ]


def _image_collection_episode(
    materials_root: Path,
    parent: Path,
    paths: list[Path],
) -> EpisodePlan:
    relative_parent = _relative_material_path(materials_root, parent)
    episode_id = _stable_episode_id(MediaType.IMAGE, relative_parent or ".")
    units = [
        _material_unit(
            materials_root,
            path,
            season_id=GENERIC_MATERIAL_SEASON_ID,
            episode_id=episode_id,
            content_form=ContentForm.IMAGE_SET,
            unit_kind="image_page" if len(paths) > 1 else "image_source",
            page_number=index,
            metadata={
                "image_collection_size": len(paths),
                "manga_candidate": len(paths) > 1,
            },
        )
        for index, path in enumerate(paths, start=1)
    ]
    collection_profile = classify_source_collection(paths)
    return EpisodePlan(
        season_id=GENERIC_MATERIAL_SEASON_ID,
        episode_id=episode_id,
        display_title=parent.name if relative_parent not in {"", "."} else materials_root.name,
        sort_key=f"image:{relative_parent.lower()}",
        content_forms=[ContentForm.IMAGE_SET],
        units=units,
        metadata={
            "scan_type": FORMAL_MATERIAL_SCAN_TYPE,
            "source_path": relative_parent,
            "collection_media_types": list(collection_profile.media_types),
            "content_form_candidates": [ContentForm.IMAGE_SET.value, ContentForm.MANGA.value],
            "manga_candidate": len(paths) > 1,
            "warnings": _unit_warnings(units),
        },
    )


def _single_material_episode(materials_root: Path, path: Path) -> EpisodePlan:
    media_type = _material_media_type(path)
    content_form = _material_content_form(path, media_type)
    relative_path = _relative_material_path(materials_root, path)
    episode_id = _stable_episode_id(media_type, relative_path)
    unit = _material_unit(
        materials_root,
        path,
        season_id=GENERIC_MATERIAL_SEASON_ID,
        episode_id=episode_id,
        content_form=content_form,
        unit_kind=_material_unit_kind(path, media_type),
    )
    collection_profile = classify_source_collection([path])
    return EpisodePlan(
        season_id=GENERIC_MATERIAL_SEASON_ID,
        episode_id=episode_id,
        display_title=path.name,
        sort_key=f"{media_type.value}:{relative_path.lower()}",
        content_forms=[content_form],
        units=[unit],
        metadata={
            "scan_type": FORMAL_MATERIAL_SCAN_TYPE,
            "source_path": relative_path,
            "collection_media_types": list(collection_profile.media_types),
            "warnings": _unit_warnings([unit]),
        },
    )


def _material_unit(
    materials_root: Path,
    path: Path,
    *,
    season_id: str,
    episode_id: str,
    content_form: ContentForm,
    unit_kind: str,
    page_number: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExtractionUnit:
    media_type = _material_media_type(path)
    relative_path = _relative_material_path(materials_root, path)
    support = source_support_profile(path)
    unit_metadata = {
        "display_title": path.name,
        "sort_key": relative_path.lower(),
        "support_reason": support.reason,
        **(metadata or {}),
    }
    if path.suffix.lower() in TIMED_TEXT_SUFFIXES:
        unit_metadata["timed_text_supported"] = (
            path.suffix.lower() in SUPPORTED_TIMED_TEXT_SUFFIXES
        )
    material_ref = MaterialRef(
        material_id=_stable_material_id(media_type, relative_path),
        relative_path=relative_path,
        source_media_type=media_type,
        content_form=content_form,
        origin=MaterialOrigin.MATERIAL,
        page_range=(
            PageRange(start_page=page_number, end_page=page_number)
            if page_number is not None
            else None
        ),
        text_range=TextRange(chapter=path.stem) if media_type == MediaType.TEXT else None,
        metadata=unit_metadata,
    )
    handler_options: dict[str, Any] = {
        "preview_support": support.preview_support.value,
        "formal_support": support.formal_support.value,
    }
    if media_type == MediaType.AUDIO:
        handler_options["transcript_candidate"] = True
    if path.suffix.lower() in TIMED_TEXT_SUFFIXES:
        handler_options.update(
            {
                "timed_text_format": path.suffix.lower().lstrip("."),
                "speaker_policy": "explicit_only",
            }
        )
    return ExtractionUnit(
        unit_id=_stable_unit_id(media_type, relative_path),
        episode_id=episode_id,
        media_type=media_type,
        content_form=content_form,
        material_ref=material_ref,
        origin=MaterialOrigin.MATERIAL,
        unit_kind=unit_kind,
        handler_options=handler_options,
        metadata={"season_id": season_id, **unit_metadata},
    )


def _material_media_type(path: Path) -> MediaType:
    media_type = source_media_type(path)
    if media_type is None or media_type == MediaType.VIDEO.value:
        raise ValueError(f"unsupported non-video material: {path}")
    return MediaType(media_type)


def _material_content_form(path: Path, media_type: MediaType) -> ContentForm:
    if media_type == MediaType.AUDIO:
        return ContentForm.AUDIO_DRAMA
    if media_type == MediaType.IMAGE:
        return ContentForm.IMAGE_SET
    if path.suffix.lower() in TIMED_TEXT_SUFFIXES:
        return ContentForm.SCRIPT
    normalized_name = path.stem.lower()
    if any(token in normalized_name for token in ("script", "screenplay", "台本", "剧本")):
        return ContentForm.SCRIPT
    if any(token in normalized_name for token in ("setting", "profile", "设定", "资料")):
        return ContentForm.SETTING_BOOK
    return ContentForm.NOVEL


def _material_unit_kind(path: Path, media_type: MediaType) -> str:
    if media_type == MediaType.TEXT:
        return _text_unit_kind(path)
    if media_type == MediaType.AUDIO:
        return "audio_source"
    return "image_source"


def _text_unit_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".srt", ".ass", ".vtt"}:
        return "subtitle_text"
    if suffix == ".lrc":
        return "lyrics_text"
    if suffix == ".json":
        return "controlled_json_text"
    return "document_text"


def _unit_warnings(units: list[ExtractionUnit]) -> list[str]:
    warnings: list[str] = []
    for unit in units:
        reason = _string(unit.material_ref.metadata.get("support_reason"))
        if reason and unit.handler_options.get("formal_support") == "unsupported":
            warnings.append(f"{unit.material_ref.relative_path}: {reason}")
    return warnings


def _relative_material_path(materials_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(materials_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _stable_material_id(media_type: MediaType, source_path: str) -> str:
    digest = sha1(f"{media_type.value}:{source_path}".encode("utf-8")).hexdigest()[:12]
    return f"material_{media_type.value}_{digest}"


def _stable_episode_id(media_type: MediaType, source_path: str) -> str:
    digest = sha1(f"episode:{media_type.value}:{source_path}".encode("utf-8")).hexdigest()[:12]
    return f"episode_{media_type.value}_{digest}"


def _stable_unit_id(media_type: MediaType, source_path: str) -> str:
    digest = sha1(f"unit:{media_type.value}:{source_path}".encode("utf-8")).hexdigest()[:12]
    return f"unit_{media_type.value}_{digest}"


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
