from __future__ import annotations

import logging
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import ChunkExtractionResult, InsightEvent, InsightStatus, ProjectConfig
from utils.ai_model_middleware import ModelBackend, ModelCallRequest, build_model_call_request, call_model
from utils.cloud_model_presets import load_cloud_model_presets
from utils.i18n import t
from utils.paths import ensure_project_tree


LOGGER = logging.getLogger(__name__)
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}


class Extractor(QObject):
    insightGenerated = pyqtSignal(dict)
    progressChanged = pyqtSignal(int)

    def scan_source_directory(self, source_root: str) -> dict:
        root = Path(source_root).expanduser()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"source root does not exist or is not a directory: {source_root}")

        season_dirs = sorted(
            [path for path in root.iterdir() if path.is_dir()],
            key=lambda path: path.name.lower(),
        )

        seasons: list[dict] = []
        for season_index, season_dir in enumerate(season_dirs, start=1):
            episode_files = sorted(
                [
                    file_path
                    for file_path in season_dir.iterdir()
                    if file_path.is_file() and file_path.suffix.lower() in VIDEO_SUFFIXES
                ],
                key=lambda path: path.name.lower(),
            )
            episodes: list[dict] = []
            for episode_index, episode_file in enumerate(episode_files, start=1):
                episodes.append(
                    {
                        "episode_id": f"episode_{episode_index:03d}",
                        "source_file": str(episode_file.resolve()),
                        "display_title": episode_file.name,
                        "sort_key": episode_file.name.lower(),
                    }
                )
            seasons.append(
                {
                    "season_id": f"season_{season_index:03d}",
                    "source_folder": str(season_dir.resolve()),
                    "display_title": season_dir.name,
                    "sort_key": season_dir.name.lower(),
                    "episodes": episodes,
                }
            )

        return {
            "source_root": str(root.resolve()),
            "seasons": seasons,
        }

    def generate_source_manifest(self, project_id: str, source_root: str) -> Path:
        manifest = self.scan_source_directory(source_root)
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        manifest_path = knowledge_base / "source_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest_path

    def initialize_knowledge_base_structure(self, project_id: str, manifest: dict | None = None) -> Path:
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        manifest_data = manifest
        if manifest_data is None:
            manifest_path = knowledge_base / "source_manifest.json"
            if not manifest_path.exists():
                raise ValueError("source manifest not found; generate source_manifest.json first")
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

        seasons = manifest_data.get("seasons", [])
        seasons_root = knowledge_base / "seasons"
        for season in seasons:
            season_id = season.get("season_id")
            if not isinstance(season_id, str) or not season_id.strip():
                continue
            episode_root = seasons_root / season_id / "episodes"
            for episode in season.get("episodes", []):
                episode_id = episode.get("episode_id")
                if not isinstance(episode_id, str) or not episode_id.strip():
                    continue
                (episode_root / episode_id / "chunks").mkdir(parents=True, exist_ok=True)
        return seasons_root

    def save_chunk_extraction_result(self, project_id: str, result: ChunkExtractionResult) -> Path:
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        chunk_dir = (
            knowledge_base
            / "seasons"
            / result.season_id
            / "episodes"
            / result.episode_id
            / "chunks"
        )
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_path = chunk_dir / f"{result.chunk_id}.json"
        chunk_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return chunk_path

    def merge_episode_content(self, project_id: str, season_id: str, episode_id: str) -> Path:
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        episode_dir = knowledge_base / "seasons" / season_id / "episodes" / episode_id
        chunk_dir = episode_dir / "chunks"
        chunk_paths = sorted(
            [path for path in chunk_dir.glob("*.json") if path.is_file()],
            key=lambda path: path.name.lower(),
        )

        chunk_results: list[dict[str, Any]] = []
        targets: list[str] = []
        facts: list[str] = []
        behavior_traits: list[str] = []
        dialogue_style: list[str] = []
        relationship_interactions: list[str] = []
        conflicts: list[str] = []
        character_state_changes: list[str] = []
        evidence_refs: list[str] = []

        for chunk_path in chunk_paths:
            payload = json.loads(chunk_path.read_text(encoding="utf-8"))
            chunk = ChunkExtractionResult.model_validate(payload)
            chunk_results.append(chunk.model_dump(mode="json"))
            targets.extend(chunk.targets)
            facts.extend(chunk.facts)
            behavior_traits.extend(chunk.behavior_traits)
            dialogue_style.extend(chunk.dialogue_style)
            relationship_interactions.extend(chunk.relationship_interactions)
            conflicts.extend(chunk.conflicts)
            character_state_changes.extend(chunk.character_state_changes)
            evidence_refs.extend(chunk.evidence_refs)

        episode_content = {
            "season_id": season_id,
            "episode_id": episode_id,
            "targets": self._deduplicate_preserve_order(targets),
            "chunk_results": chunk_results,
            "facts": self._deduplicate_preserve_order(facts),
            "behavior_traits": self._deduplicate_preserve_order(behavior_traits),
            "dialogue_style": self._deduplicate_preserve_order(dialogue_style),
            "relationship_interactions": self._deduplicate_preserve_order(relationship_interactions),
            "conflicts": self._deduplicate_preserve_order(conflicts),
            "character_state_changes": self._deduplicate_preserve_order(character_state_changes),
            "evidence_refs": self._deduplicate_preserve_order(evidence_refs),
        }
        output_path = episode_dir / "episode_content.json"
        output_path.write_text(json.dumps(episode_content, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def generate_episode_summary(self, project_id: str, season_id: str, episode_id: str) -> Path:
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        episode_dir = knowledge_base / "seasons" / season_id / "episodes" / episode_id
        episode_content_path = episode_dir / "episode_content.json"
        if not episode_content_path.exists():
            raise ValueError("episode content not found; merge episode content first")

        episode_content = json.loads(episode_content_path.read_text(encoding="utf-8"))
        chunk_results = episode_content.get("chunk_results", [])
        insight_summaries: list[str] = []
        for chunk in chunk_results:
            if not isinstance(chunk, dict):
                continue
            insight = chunk.get("insight_summary", "")
            if isinstance(insight, str) and insight.strip():
                insight_summaries.append(insight.strip())

        summary = {
            "season_id": season_id,
            "episode_id": episode_id,
            "character_summaries": episode_content.get("behavior_traits", []),
            "relationship_changes": episode_content.get("relationship_interactions", []),
            "major_events": episode_content.get("facts", []),
            "open_conflicts": episode_content.get("conflicts", []),
            "growth_signals": episode_content.get("character_state_changes", []),
            "insight_summary": " | ".join(self._deduplicate_preserve_order(insight_summaries)),
        }
        summary_path = episode_dir / "episode_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary_path

    def merge_season_content(self, project_id: str, season_id: str) -> Path:
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        episodes_root = knowledge_base / "seasons" / season_id / "episodes"
        if not episodes_root.exists():
            raise ValueError("season episodes not found; initialize knowledge base structure first")

        episode_contents: list[dict[str, Any]] = []
        targets: list[str] = []
        facts: list[str] = []
        behavior_traits: list[str] = []
        dialogue_style: list[str] = []
        relationship_interactions: list[str] = []
        conflicts: list[str] = []
        character_state_changes: list[str] = []
        evidence_refs: list[str] = []

        for episode_dir in sorted([path for path in episodes_root.iterdir() if path.is_dir()], key=lambda p: p.name.lower()):
            episode_content_path = episode_dir / "episode_content.json"
            if not episode_content_path.exists():
                continue
            payload = json.loads(episode_content_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            episode_contents.append(payload)
            targets.extend(payload.get("targets", []))
            facts.extend(payload.get("facts", []))
            behavior_traits.extend(payload.get("behavior_traits", []))
            dialogue_style.extend(payload.get("dialogue_style", []))
            relationship_interactions.extend(payload.get("relationship_interactions", []))
            conflicts.extend(payload.get("conflicts", []))
            character_state_changes.extend(payload.get("character_state_changes", []))
            evidence_refs.extend(payload.get("evidence_refs", []))

        season_content = {
            "season_id": season_id,
            "episode_contents": episode_contents,
            "targets": self._deduplicate_preserve_order(targets),
            "facts": self._deduplicate_preserve_order(facts),
            "behavior_traits": self._deduplicate_preserve_order(behavior_traits),
            "dialogue_style": self._deduplicate_preserve_order(dialogue_style),
            "relationship_interactions": self._deduplicate_preserve_order(relationship_interactions),
            "conflicts": self._deduplicate_preserve_order(conflicts),
            "character_state_changes": self._deduplicate_preserve_order(character_state_changes),
            "evidence_refs": self._deduplicate_preserve_order(evidence_refs),
        }
        season_dir = knowledge_base / "seasons" / season_id
        season_content_path = season_dir / "season_content.json"
        season_content_path.write_text(json.dumps(season_content, ensure_ascii=False, indent=2), encoding="utf-8")
        return season_content_path

    def _deduplicate_preserve_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            unique_values.append(value)
        return unique_values

    def _build_chunk_payload(
        self,
        chunk_text: str,
        *,
        previous_episode_summary: str = "",
        previous_chunk_insights: list[str] | None = None,
        previous_episode_extracted_chunks: list[ChunkExtractionResult | dict[str, Any]] | None = None,
        current_season_episode_summaries: list[dict[str, Any]] | None = None,
        max_previous_chunks: int = 3,
    ) -> str:
        sections = [f"[CURRENT_CHUNK]\n{chunk_text.strip()}"]
        if previous_episode_extracted_chunks:
            structured_chunks: list[dict[str, Any]] = []
            for item in previous_episode_extracted_chunks:
                if isinstance(item, ChunkExtractionResult):
                    structured_chunks.append(item.model_dump(mode="json"))
                elif isinstance(item, dict):
                    structured_chunks.append(item)
            if structured_chunks:
                sections.append(
                    "[CURRENT_EPISODE_EXTRACTED_CHUNKS]\n"
                    + json.dumps(structured_chunks, ensure_ascii=False, indent=2)
                )
        if current_season_episode_summaries:
            sections.append(
                "[CURRENT_SEASON_EPISODE_SUMMARIES]\n"
                + json.dumps(current_season_episode_summaries, ensure_ascii=False, indent=2)
            )
        if previous_episode_summary.strip():
            sections.append(f"[PREVIOUS_EPISODE_SUMMARY]\n{previous_episode_summary.strip()}")
        if previous_chunk_insights:
            trimmed = [item.strip() for item in previous_chunk_insights if item.strip()]
            if trimmed:
                recent = trimmed[-max_previous_chunks:]
                joined = "\n".join(f"- {item}" for item in recent)
                sections.append(f"[PREVIOUS_CHUNK_INSIGHTS]\n{joined}")
        return "\n\n".join(sections)

    def build_targeted_insight_request(
        self,
        config: ProjectConfig,
        chunk_text: str,
        *,
        previous_episode_summary: str = "",
        previous_chunk_insights: list[str] | None = None,
        previous_episode_extracted_chunks: list[ChunkExtractionResult | dict[str, Any]] | None = None,
        current_season_episode_summaries: list[dict[str, Any]] | None = None,
        backend: ModelBackend,
        model_name: str,
        base_url: str = "",
        api_key: str = "",
    ) -> ModelCallRequest:
        targets = config.target_characters or [t("extractor.noTarget")]
        payload = self._build_chunk_payload(
            chunk_text,
            previous_episode_summary=previous_episode_summary,
            previous_chunk_insights=previous_chunk_insights,
            previous_episode_extracted_chunks=previous_episode_extracted_chunks,
            current_season_episode_summaries=current_season_episode_summaries,
        )
        return build_model_call_request(
            purpose="targeted_insight",
            backend=backend,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            variables={
                "target_characters": targets,
                "chunk_text": payload,
            },
            metadata={
                "project_id": config.project_id,
                "extraction_mode": config.extraction_mode.value,
            },
        )

    def load_current_season_episode_summaries(
        self,
        project_id: str,
        season_id: str,
        current_episode_id: str,
    ) -> list[dict[str, Any]]:
        knowledge_base = ensure_project_tree(project_id).knowledge_base
        episodes_root = knowledge_base / "seasons" / season_id / "episodes"
        if not episodes_root.exists():
            return []

        summaries: list[dict[str, Any]] = []
        for episode_dir in sorted([path for path in episodes_root.iterdir() if path.is_dir()], key=lambda p: p.name.lower()):
            episode_id = episode_dir.name
            if episode_id >= current_episode_id:
                continue
            summary_path = episode_dir / "episode_summary.json"
            if not summary_path.exists():
                continue
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                summaries.append(payload)
        return summaries

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
