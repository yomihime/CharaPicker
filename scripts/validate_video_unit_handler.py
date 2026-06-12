from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.video_unit_handler import VideoUnitHandler, VideoUnitHandlerConfig  # noqa: E402
from utils.cloud_model_presets import scale_cloud_max_output_tokens_for_video_duration  # noqa: E402


def _handler(video_input_mode: str = "video_file") -> VideoUnitHandler:
    return VideoUnitHandler(
        VideoUnitHandlerConfig(
            provider="openai_compatible",
            video_fps=1.0,
            video_input_mode=video_input_mode,
            max_output_tokens_per_minute=1200,
        ),
        duration_probe=lambda _path: 120.0,
    )


def _chunk_input(video_path: Path) -> dict:
    return {
        "season_id": "season_001",
        "episode_id": "episode_001",
        "chunk_id": "chunk_0001",
        "source_path": "Episode 01/segment_0001.mp4",
        "video_path": video_path,
    }


def _assert_budget_scales_by_duration() -> None:
    with TemporaryDirectory(prefix="charapicker-video-handler-") as temp_dir:
        video_path = Path(temp_dir) / "segment_0001.mp4"
        video_path.write_bytes(b"video")
        budget = _handler().prepare_budget(video_path)
        assert budget.duration_seconds == 120.0
        assert budget.request_max_output_tokens == scale_cloud_max_output_tokens_for_video_duration(
            1200,
            120.0,
        )


def _assert_request_modes() -> None:
    with TemporaryDirectory(prefix="charapicker-video-handler-") as temp_dir:
        video_path = Path(temp_dir) / "segment_0001.mp4"
        video_path.write_bytes(b"video")
        handler = _handler("video_file")
        request = handler.build_formal_chunk_request(
            project_id="validation-project",
            chunk_input=_chunk_input(video_path),
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid",
            api_key="",
            request_max_output_tokens=2048,
            formal_context={"context_policy": {"mode": "validation"}},
        )
        assert request.max_tokens == 2048
        assert request.metadata["video_input_mode"] == "video_file"
        assert request.metadata["context_policy"] == {"mode": "validation"}
        user_parts = request.messages[1].content
        assert isinstance(user_parts, list)
        assert any("video" in part for part in user_parts if isinstance(part, dict))

        audio_only = _handler("audio_transcript_only")
        audio_request = audio_only.build_formal_chunk_request(
            project_id="validation-project",
            chunk_input=_chunk_input(video_path),
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid",
            api_key="",
            request_max_output_tokens=1024,
            transcript_context="hello",
        )
        audio_parts = audio_request.messages[1].content
        assert isinstance(audio_parts, list)
        assert not any("video" in part for part in audio_parts if isinstance(part, dict))
        assert audio_only.requires_transcript() is True


def main() -> None:
    _assert_budget_scales_by_duration()
    _assert_request_modes()
    print("video unit handler validation passed")


if __name__ == "__main__":
    main()
