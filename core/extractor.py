from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import InsightEvent, InsightStatus, ProjectConfig
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, build_model_call_request, call_model
from utils.cloud_model_presets import load_cloud_model_presets
from utils.i18n import t


LOGGER = logging.getLogger(__name__)


class Extractor(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)

    def build_targeted_insight_request(
        self,
        config: ProjectConfig,
        chunk_text: str,
        *,
        backend: ModelBackend,
        model_name: str,
        base_url: str = "",
        api_key: str = "",
    ) -> ModelCallRequest:
        targets = config.target_characters or [t("extractor.noTarget")]
        return build_model_call_request(
            purpose="targeted_insight",
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables={
                "target_characters": targets,
                "chunk_text": chunk_text,
            },
            metadata={
                "project_id": config.project_id,
                "extraction_mode": config.extraction_mode.value,
            },
        )

    def run_preview(self, config: ProjectConfig) -> None:
        self.run_preview_streaming(config)

    def run_preview_streaming(
        self,
        config: ProjectConfig,
        *,
        emit_event: Callable[[dict], None] | None = None,
        emit_progress: Callable[[int], None] | None = None,
        emit_token_usage: Callable[[dict[str, int]], None] | None = None,
    ) -> str:
        emit_event = emit_event or self.insightGenerated.emit
        emit_progress = emit_progress or self.progressChanged.emit

        targets = ", ".join(config.target_characters) or t("extractor.noTarget")
        LOGGER.info(
            "Preview extraction started; project_id=%s targets=%s sources=%s mode=%s",
            config.project_id,
            len(config.target_characters),
            len(config.source_paths),
            config.extraction_mode.value,
        )
        emit_event(
            InsightEvent(
                title=t("extractor.config.title"),
                description=t("extractor.config.description", targets=targets),
                status=InsightStatus.DONE,
            ).model_dump(mode="json")
        )
        emit_progress(15)

        presets = load_cloud_model_presets()
        preset = next((item for item in presets if item.base_url.strip() and item.model_name.strip()), None)
        if preset is None:
            emit_event(
                InsightEvent(
                    title=t("extractor.chunk.title"),
                    description=t("extractor.chunk.description"),
                    status=InsightStatus.RUNNING,
                ).model_dump(mode="json")
            )
            emit_progress(70)
            emit_event(
                InsightEvent(
                    title=t("extractor.insight.title"),
                    description=t("extractor.insight.description"),
                    status=InsightStatus.QUEUED,
                ).model_dump(mode="json")
            )
            emit_progress(100)
            LOGGER.info("Preview extraction finished without cloud preset; project_id=%s", config.project_id)
            return ""

        # TODO: Replace this metadata-only placeholder with real source ingestion:
        # read project materials, chunk text/video transcripts, and pass actual chunk content.
        source_hint = ", ".join(config.source_paths[:5]) if config.source_paths else "no source path"
        chunk_text = (
            f"Project={config.name}; mode={config.extraction_mode.value}; "
            f"targets={targets}; sources={source_hint}"
        )
        request = self.build_targeted_insight_request(
            config,
            chunk_text,
            backend="openai_compatible",
            model_name=preset.model_name,
            base_url=preset.base_url,
            api_key=preset.api_key,
        )
        request.stream = True
        request.max_tokens = 220

        emit_event(
            InsightEvent(
                title=t("extractor.chunk.title"),
                description=t("extractor.chunk.description"),
                status=InsightStatus.RUNNING,
            ).model_dump(mode="json")
        )
        emit_progress(30)

        stream_text = ""
        stream_chars = 0
        stream_id = "preview_targeted_insight"
        emit_event(
            InsightEvent(
                title=t("extractor.insight.title"),
                description="",
                status=InsightStatus.RUNNING,
                meta={"stream_id": stream_id, "update": True},
            ).model_dump(mode="json")
        )

        def _on_stream_delta(delta: str) -> None:
            nonlocal stream_text, stream_chars
            stream_chars += len(delta)
            emit_progress(min(95, 30 + stream_chars // 4))
            stream_text += delta
            emit_event(
                InsightEvent(
                    title=t("extractor.insight.title"),
                    description=stream_text.strip(),
                    status=InsightStatus.RUNNING,
                    meta={"stream_id": stream_id, "update": True},
                ).model_dump(mode="json")
            )
            if emit_token_usage is not None:
                emit_token_usage({"char_count": stream_chars})

        result = call_model(request, on_stream_delta=_on_stream_delta)
        final_text = result.content.strip()
        emit_event(
            InsightEvent(
                title=t("extractor.insight.title"),
                description=final_text or t("extractor.insight.description"),
                status=InsightStatus.DONE,
                meta={"stream_id": stream_id, "update": True},
            ).model_dump(mode="json")
        )
        token_usage = result.metadata.get("token_usage")
        if emit_token_usage is not None and isinstance(token_usage, dict):
            normalized: dict[str, int] = {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = token_usage.get(key)
                if isinstance(value, int):
                    normalized[key] = value
            if normalized:
                emit_token_usage(normalized)
        emit_progress(100)
        LOGGER.info("Preview extraction finished; project_id=%s", config.project_id)
        return final_text
