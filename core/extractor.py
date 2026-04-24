from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import InsightEvent, InsightStatus, ProjectConfig
from utils.i18n import t


class Extractor(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)

    def run_preview(self, config: ProjectConfig) -> None:
        targets = ", ".join(config.target_characters) or t("extractor.noTarget")
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
