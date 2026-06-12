from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.ai_model_middleware import (
    ModelBackend,
    ModelCallRequest,
    ModelMessage,
    render_prompt_texts,
)
from utils.cloud_model_presets import (
    VideoInputMode,
    provider_requires_aliyun_extra_body,
    scale_cloud_max_output_tokens_for_video_duration,
)
from utils.ffmpeg_tool import FfmpegProcessError, probe_video_duration_seconds
from utils.i18n import t


LOGGER = logging.getLogger(__name__)
DurationProbe = Callable[[Path], float]


@dataclass(frozen=True, slots=True)
class VideoUnitBudget:
    duration_seconds: float
    request_max_output_tokens: int


@dataclass(frozen=True, slots=True)
class VideoUnitHandlerConfig:
    provider: str
    video_fps: float
    video_input_mode: VideoInputMode
    max_output_tokens_per_minute: int


class VideoUnitHandler:
    def __init__(
        self,
        config: VideoUnitHandlerConfig,
        *,
        duration_probe: DurationProbe = probe_video_duration_seconds,
    ) -> None:
        self.config = config
        self._duration_probe = duration_probe

    def requires_transcript(self) -> bool:
        return self.video_mode_requires_transcript(self.config.video_input_mode)

    @staticmethod
    def video_mode_requires_transcript(video_input_mode: VideoInputMode) -> bool:
        return video_input_mode in {"frame_sampling_with_transcript", "audio_transcript_only"}

    def prepare_budget(self, video_path: Path) -> VideoUnitBudget:
        duration_seconds = self.duration_seconds(video_path)
        request_max_output_tokens = scale_cloud_max_output_tokens_for_video_duration(
            self.config.max_output_tokens_per_minute,
            duration_seconds,
        )
        return VideoUnitBudget(
            duration_seconds=duration_seconds,
            request_max_output_tokens=request_max_output_tokens,
        )

    def duration_seconds(self, video_path: Path) -> float:
        try:
            return self._duration_probe(video_path)
        except (FfmpegProcessError, OSError):
            LOGGER.warning(
                "Video chunk duration probe failed; chunk=%s",
                video_path.name,
                exc_info=True,
            )
            return 60.0

    def build_formal_chunk_request(
        self,
        *,
        project_id: str,
        chunk_input: dict[str, Any],
        backend: ModelBackend,
        model_name: str,
        base_url: str,
        api_key: str,
        request_max_output_tokens: int,
        transcript_context: str = "",
        formal_context: dict[str, Any] | None = None,
    ) -> ModelCallRequest:
        video_path = chunk_input["video_path"]
        context = formal_context or {}
        system_prompt, user_text = render_prompt_texts(
            purpose="formal_contextual_video_chunk_extraction",
            variables={
                "season_id": chunk_input["season_id"],
                "episode_id": chunk_input["episode_id"],
                "chunk_id": chunk_input["chunk_id"],
                "source_path": chunk_input["source_path"],
                "transcript_section": self._format_transcript_prompt_section(transcript_context),
                "current_episode_extracted_chunks": context.get(
                    "current_episode_extracted_chunks",
                    [],
                ),
                "current_season_completed_episodes": context.get(
                    "current_season_completed_episodes",
                    [],
                ),
                "previous_season_backgrounds": context.get(
                    "previous_season_backgrounds",
                    [],
                ),
            },
        )
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if self.config.video_input_mode != "audio_transcript_only":
            content_parts.append(self._build_video_chunk_part(video_path))
        return ModelCallRequest(
            purpose="formal_contextual_video_chunk_extraction",
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            messages=[
                ModelMessage(role="system", content=system_prompt),
                ModelMessage(role="user", content=content_parts),
            ],
            temperature=0.2,
            max_tokens=request_max_output_tokens,
            stream=False,
            timeout_seconds=240,
            response_format={"type": "json_object"},
            extra_body=self._video_model_extra_body(),
            metadata={
                "project_id": project_id,
                "stage": "full_chunk_extraction",
                "season_id": chunk_input["season_id"],
                "episode_id": chunk_input["episode_id"],
                "chunk_id": chunk_input["chunk_id"],
                "source_path": chunk_input["source_path"],
                "video_input_mode": self.config.video_input_mode,
                "context_policy": context.get("context_policy", {}),
            },
        )

    def _build_video_chunk_part(self, video_path: Path) -> dict[str, Any]:
        return {"video": f"file://{video_path.resolve().as_posix()}", "fps": self.config.video_fps}

    def _format_transcript_prompt_section(self, transcript_context: str) -> str:
        if not self.requires_transcript():
            return ""
        context = transcript_context.strip() or t("extractor.transcript.context.empty")
        if self.config.video_input_mode == "audio_transcript_only":
            note = t("extractor.transcript.prompt.audioOnly")
        else:
            note = t("extractor.transcript.prompt.withFrames")
        return f"[TRANSCRIPT_CONTEXT]\n{context}\n\n{note}"

    def _video_model_extra_body(self) -> dict[str, Any]:
        if provider_requires_aliyun_extra_body(self.config.provider):
            return {"enable_thinking": False}
        return {}
