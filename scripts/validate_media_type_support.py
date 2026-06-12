from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.media_types import (  # noqa: E402
    AUDIO_SUFFIXES,
    DEFERRED_TIMED_TEXT_SUFFIXES,
    IMAGE_SUFFIXES,
    SUPPORTED_TIMED_TEXT_SUFFIXES,
    SUPPORTED_SOURCE_SUFFIXES,
    TEXT_SUFFIXES,
    VIDEO_SUFFIXES,
    SourceSupportLevel,
    classify_source_collection,
    is_import_supported_source,
    source_media_type,
    source_support_profile,
)
from utils.source_importer import _expand_source_paths  # noqa: E402


LEGACY_VIDEO_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".flv",
    ".wmv",
    ".m4v",
}


def _assert_suffix_matrix() -> None:
    assert VIDEO_SUFFIXES == LEGACY_VIDEO_SUFFIXES
    assert AUDIO_SUFFIXES <= SUPPORTED_SOURCE_SUFFIXES
    assert IMAGE_SUFFIXES <= SUPPORTED_SOURCE_SUFFIXES
    assert TEXT_SUFFIXES <= SUPPORTED_SOURCE_SUFFIXES
    assert source_media_type("episode.mp4") == "video"
    assert source_media_type("portrait.PNG") == "image"
    assert source_media_type("voice.flac") == "audio"
    assert source_media_type("dialogue.srt") == "text"
    assert SUPPORTED_TIMED_TEXT_SUFFIXES == {".srt", ".ass"}
    assert DEFERRED_TIMED_TEXT_SUFFIXES == {".vtt", ".lrc"}


def _assert_special_support_states() -> None:
    gif_profile = source_support_profile("scene.gif")
    assert gif_profile.import_supported is True
    assert gif_profile.preview_support == SourceSupportLevel.UNSUPPORTED
    assert gif_profile.formal_support == SourceSupportLevel.UNSUPPORTED
    assert gif_profile.reason == "animated_image_not_supported"

    json_profile = source_support_profile("setting.json")
    assert json_profile.import_supported is True
    assert json_profile.reason == "controlled_json_only"

    for suffix in SUPPORTED_TIMED_TEXT_SUFFIXES:
        profile = source_support_profile(f"dialogue{suffix}")
        assert profile.preview_support == SourceSupportLevel.SUPPORTED
        assert profile.formal_support == SourceSupportLevel.SUPPORTED

    vtt_profile = source_support_profile("dialogue.vtt")
    assert vtt_profile.preview_support == SourceSupportLevel.UNSUPPORTED
    assert vtt_profile.formal_support == SourceSupportLevel.UNSUPPORTED
    assert vtt_profile.reason == "vtt_timed_text_not_supported"

    lrc_profile = source_support_profile("lyrics.lrc")
    assert lrc_profile.preview_support == SourceSupportLevel.UNSUPPORTED
    assert lrc_profile.formal_support == SourceSupportLevel.UNSUPPORTED
    assert lrc_profile.reason == "lrc_timed_text_not_supported"

    archive_profile = source_support_profile("chapter.cbz")
    assert archive_profile.import_supported is False
    assert archive_profile.reason == "comic_archive_not_supported"

    unknown_profile = source_support_profile("notes.custom")
    assert unknown_profile.import_supported is False
    assert is_import_supported_source("README") is True
    assert source_media_type("README") is None


def _assert_collection_hints() -> None:
    images = classify_source_collection(["001.png", "002.jpg"])
    assert images.media_types == ("image",)
    assert images.content_form_hint == "image_set"

    timed_text = classify_source_collection(["episode.srt", "episode.ass"])
    assert timed_text.media_types == ("text",)
    assert timed_text.content_form_hint == "script"

    mixed = classify_source_collection(["episode.mp4", "episode.srt", "poster.png"])
    assert mixed.media_types == ("video", "image", "text")
    assert mixed.content_form_hint == "mixed"

    unsupported = classify_source_collection(["chapter.cbz", "notes.custom"])
    assert tuple(path.name for path in unsupported.unsupported_paths) == (
        "chapter.cbz",
        "notes.custom",
    )


def _assert_importer_uses_support_matrix() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "sources"
        root.mkdir()
        for name in (
            "episode.mp4",
            "voice.wav",
            "poster.png",
            "dialogue.srt",
            "animation.gif",
            "chapter.cbz",
            "notes.custom",
        ):
            (root / name).write_bytes(b"fixture")

        imported_names = {target.path.name for target in _expand_source_paths([str(root)])}
        assert imported_names == {
            "episode.mp4",
            "voice.wav",
            "poster.png",
            "dialogue.srt",
            "animation.gif",
        }


def main() -> None:
    _assert_suffix_matrix()
    _assert_special_support_states()
    _assert_collection_hints()
    _assert_importer_uses_support_matrix()
    print("media type support validation passed")


if __name__ == "__main__":
    main()
