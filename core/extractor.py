from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import InsightEvent, InsightStatus, ProjectConfig


class Extractor(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)

    def run_preview(self, config: ProjectConfig) -> None:
        targets = ", ".join(config.target_characters) or "未指定角色"
        events = [
            InsightEvent(
                title="读取项目配置",
                description=f"目标角色: {targets}",
                status=InsightStatus.DONE,
            ),
            InsightEvent(
                title="抽样切片",
                description="预览模式会先取前 2 个 chunk，用于检查提示词和证据质量。",
                status=InsightStatus.RUNNING,
            ),
            InsightEvent(
                title="定向洞察",
                description="等待接入 AI 后，将写入 knowledge_base/targeted_insights.json。",
                status=InsightStatus.QUEUED,
            ),
        ]
        for index, event in enumerate(events, start=1):
            self.insightGenerated.emit(event.model_dump(mode="json"))
            self.progressChanged.emit(round(index / len(events) * 100))
