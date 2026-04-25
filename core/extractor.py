from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import InsightEvent, InsightStatus, ProjectConfig
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, build_model_call_request
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
        targets = ", ".join(config.target_characters) or t("extractor.noTarget")
        LOGGER.info(
            "Preview extraction started; project_id=%s targets=%s sources=%s mode=%s",
            config.project_id,
            len(config.target_characters),
            len(config.source_paths),
            config.extraction_mode.value,
        )
        events = [
            InsightEvent(
                title=t("extractor.config.title"),
                description=t("extractor.config.description", targets=targets),
                status=InsightStatus.DONE,
            ),
            InsightEvent(
                title=t("extractor.chunk.title"),
                description=t("extractor.chunk.description"),
                status=InsightStatus.RUNNING,
            ),
            InsightEvent(
                title=t("extractor.insight.title"),
                description=t("extractor.insight.description"),
                status=InsightStatus.QUEUED,
            ),
        ]
        for index, event in enumerate(events, start=1):
            self.insightGenerated.emit(event.model_dump(mode="json"))
            self.progressChanged.emit(round(index / len(events) * 100))
            LOGGER.debug(
                "Preview extraction event emitted; project_id=%s index=%s status=%s",
                config.project_id,
                index,
                event.status.value,
            )
        LOGGER.info("Preview extraction finished; project_id=%s", config.project_id)
