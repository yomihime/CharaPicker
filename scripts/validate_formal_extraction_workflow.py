from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core import knowledge_base as kb  # noqa: E402
from core.character_card_store import (  # noqa: E402
    load_card,
    mark_compiled_official_cards_stale,
    save_card,
)
from core.extraction_ai import (  # noqa: E402
    FormalExtractionJsonError,
    FormalExtractionOutputTruncatedError,
    call_formal_json_model,
)
from core.extractor import Extractor  # noqa: E402
from core.models import (  # noqa: E402
    CharacterCard,
    CharacterCardKind,
    CharacterCardStatus,
    ExtractionArtifactStage,
    ExtractionMode,
    ProjectConfig,
    ProjectPaths,
)
from utils.ai_model_middleware import ModelCallRequest, ModelCallResult, ModelMessage  # noqa: E402


@contextmanager
def _isolated_project_tree(project_id: str = "validation-project") -> Iterator[ProjectPaths]:
    original_ensure_project_tree = kb.ensure_project_tree
    with TemporaryDirectory(prefix="charapicker-validation-") as temp_dir:
        projects_root = Path(temp_dir) / "projects"

        def fake_ensure_project_tree(requested_project_id: str) -> ProjectPaths:
            root = projects_root / requested_project_id
            knowledge_base = root / "knowledge_base"
            paths = ProjectPaths(
                root=root,
                raw=root / "raw",
                materials=root / "materials",
                cache=root / "cache",
                knowledge_base=knowledge_base,
                output=root / "output",
                config=root / "config.json",
                facts=knowledge_base / "facts.json",
                targeted_insights=knowledge_base / "targeted_insights.json",
            )
            for directory in (
                paths.raw,
                paths.materials,
                paths.cache,
                paths.knowledge_base,
                paths.output,
            ):
                directory.mkdir(parents=True, exist_ok=True)
            return paths

        kb.ensure_project_tree = fake_ensure_project_tree
        try:
            yield fake_ensure_project_tree(project_id)
        finally:
            kb.ensure_project_tree = original_ensure_project_tree


def _assert_fast_concurrency_bounds() -> None:
    extractor = Extractor()
    inputs = [None, 0, 1, 3, 500, 501, "bad"]
    expected = [1, 1, 1, 3, 500, 500, 1]
    actual = [extractor._normalize_fast_concurrency(value) for value in inputs]
    assert actual == expected, actual


def _assert_formal_json_retry_success_on_third_attempt() -> None:
    attempts = {"count": 0}
    request = ModelCallRequest(
        purpose="validation",
        backend="openai_compatible",
        model_name="validation-model",
        messages=[ModelMessage(role="user", content="return json")],
        max_tokens=128,
    )

    def fake_call(_request: ModelCallRequest) -> ModelCallResult:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return ModelCallResult(
                content="not json",
                metadata={
                    "token_usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 0,
                        "total_tokens": 1,
                    }
                },
            )
        return ModelCallResult(
            content='{"ok": true}',
            metadata={
                "token_usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                }
            },
        )

    result = call_formal_json_model(request, call_model=fake_call)
    assert result.payload == {"ok": True}
    assert result.attempts == 3
    assert result.token_usage == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert result.model_metadata["attempt_count"] == 3
    assert len(result.model_metadata["attempts"]) == 3
    assert result.model_metadata["token_usage_incomplete"] is False
    assert result.model_metadata["successful_attempt_token_usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }
    assert attempts["count"] == 3


def _assert_formal_json_retry_fails_after_three_attempts() -> None:
    request = ModelCallRequest(
        purpose="validation",
        backend="openai_compatible",
        model_name="validation-model",
        messages=[ModelMessage(role="user", content="return json")],
        max_tokens=128,
    )

    def fake_call(_request: ModelCallRequest) -> ModelCallResult:
        return ModelCallResult(content="still not json")

    try:
        call_formal_json_model(request, call_model=fake_call)
    except FormalExtractionJsonError as exc:
        assert exc.attempts == 3
        assert len(exc.attempt_metadata) == 3
        return
    raise AssertionError("expected FormalExtractionJsonError after three attempts")


def _assert_formal_json_output_limit_stops_without_retry() -> None:
    request = ModelCallRequest(
        purpose="validation",
        backend="openai_compatible",
        model_name="validation-model",
        messages=[ModelMessage(role="user", content="return json")],
        max_tokens=128,
    )

    def fake_call(_request: ModelCallRequest) -> ModelCallResult:
        return ModelCallResult(
            content='{"partial": true',
            raw={"choices": [{"finish_reason": "length"}]},
            metadata={"token_usage": {"prompt_tokens": 3, "completion_tokens": 128}},
        )

    try:
        call_formal_json_model(request, call_model=fake_call)
    except FormalExtractionOutputTruncatedError as exc:
        assert exc.attempts == 1
        assert exc.last_content == '{"partial": true'
        assert len(exc.attempt_metadata) == 1
        metadata = exc.attempt_metadata[0]
        assert metadata["finish_reason"] == "length"
        assert metadata["output_truncated"] is True
        assert metadata["requested_output_tokens"] == 128
        assert metadata["token_usage"] == {"prompt_tokens": 3, "completion_tokens": 128}
        return
    raise AssertionError("expected FormalExtractionOutputTruncatedError for length finish_reason")


def _assert_fast_episode_and_season_skip_without_inputs() -> None:
    extractor = Extractor()
    config = ProjectConfig(project_id="validation-project", extraction_mode=ExtractionMode.FAST)
    manifest = {
        "extraction_run_id": "run-validation",
        "seasons": [{"season_id": "season_001", "episodes": [{"episode_id": "episode_001"}]}],
    }
    chunk_inputs = [
        {
            "season_id": "season_001",
            "episode_id": "episode_001",
            "chunk_id": "chunk_0001",
        }
    ]

    episode_usage, episode_stats = extractor._finalize_fast_episode_contexts_from_chunks(
        config,
        manifest,
        chunk_inputs=chunk_inputs,
        extracted_chunks=[],
        concurrency=999,
        backend="openai_compatible",
        model_name="validation-model",
        base_url="",
        api_key="",
        context_window_tokens=None,
    )
    assert episode_usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert episode_stats == {
        "succeeded_episodes": 0,
        "skipped_episodes": 1,
        "failed_episodes": 0,
    }

    season_usage, season_stats = extractor._finalize_fast_season_contexts_from_episodes(
        config,
        manifest,
        concurrency=999,
        backend="openai_compatible",
        model_name="validation-model",
        base_url="",
        api_key="",
        context_window_tokens=None,
    )
    assert season_usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert season_stats == {
        "succeeded_seasons": 0,
        "skipped_seasons": 1,
        "failed_seasons": 0,
    }


def _assert_full_extraction_modes_stop_before_completion_without_chunks() -> None:
    project_id = "validation-empty-formal-materials"
    with _isolated_project_tree(project_id):
        cases = [
            (ExtractionMode.FULL, ExtractionMode.FULL),
            (ExtractionMode.CLEAN, ExtractionMode.CLEAN),
            (ExtractionMode.FAST, ExtractionMode.FAST),
        ]
        for configured_mode, expected_plan_mode in cases:
            extractor = Extractor()
            progress: list[int] = []
            events: list[dict] = []
            plan_modes: list[ExtractionMode] = []

            def fake_prepare_formal_video_extraction_plan(
                _project_id: str,
                *,
                mode: ExtractionMode,
            ) -> dict:
                plan_modes.append(mode)
                return {"extraction_run_id": f"run-{configured_mode.value}", "seasons": []}

            extractor.prepare_formal_video_extraction_plan = fake_prepare_formal_video_extraction_plan
            extractor._collect_formal_video_chunk_inputs = lambda _project_id, _manifest: []

            config = ProjectConfig(project_id=project_id, extraction_mode=configured_mode)
            try:
                extractor.run_full_extraction_streaming(
                    config,
                    cloud_preset=None,
                    emit_event=lambda event: events.append(event),
                    emit_progress=lambda value: progress.append(value),
                    emit_token_usage=lambda _usage: None,
                )
            except ValueError as exc:
                assert "materials/" in str(exc)
            else:
                raise AssertionError(f"expected {configured_mode.value} mode to stop without chunks")

            assert plan_modes == [expected_plan_mode]
            assert progress
            assert max(progress) < 100
            assert any(event.get("status") == "warning" for event in events)


def _write_chunk_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kb.write_json(path, payload)


def _assert_run_artifact_filtering() -> None:
    project_id = "validation-run-filtering"
    with _isolated_project_tree(project_id):
        chunks_root = kb.chunks_root_path(project_id, "season_001", "episode_001")
        current_full = chunks_root / "chunk_current.json"
        old_full = chunks_root / "chunk_old.json"
        preview_chunk = chunks_root / "preview__chunk_preview.json"
        legacy_chunk = chunks_root / "chunk_legacy.json"

        current_payload = {
            "extraction_stage": ExtractionArtifactStage.FULL.value,
            "extraction_run_id": "run-current",
        }
        old_payload = {
            "extraction_stage": ExtractionArtifactStage.FULL.value,
            "extraction_run_id": "run-old",
        }
        preview_payload = {
            "extraction_stage": ExtractionArtifactStage.PREVIEW.value,
            "extraction_run_id": "run-current",
        }
        legacy_payload = {"chunk_id": "legacy_without_stage"}

        _write_chunk_payload(current_full, current_payload)
        _write_chunk_payload(old_full, old_payload)
        _write_chunk_payload(preview_chunk, preview_payload)
        _write_chunk_payload(legacy_chunk, legacy_payload)

        filtered = kb.list_full_chunk_result_paths_for_run(project_id, "run-current")
        assert filtered == [current_full], filtered
        assert kb.is_full_artifact_payload_for_run(current_payload, "run-current") is True
        assert kb.is_full_artifact_payload_for_run(old_payload, "run-current") is False
        assert kb.is_full_artifact_payload_for_run(preview_payload, "run-current") is False
        assert kb.is_full_artifact_payload_for_run(legacy_payload, "run-current") is False
        assert kb.is_matching_run_artifact_payload(old_payload, "") is True


def _assert_clean_regenerable_artifacts_scope() -> None:
    project_id = "validation-clean-scope"
    with _isolated_project_tree(project_id) as paths:
        regenerable_paths = [
            kb.source_manifest_path(project_id),
            kb.season_path(project_id, "season_001") / "season_content.json",
            kb.season_path(project_id, "season_001") / "season_summary.json",
            kb.season_path(project_id, "season_001") / "character_stage_states.json",
            kb.episode_path(project_id, "season_001", "episode_001") / "episode_content.json",
            kb.episode_path(project_id, "season_001", "episode_001") / "preview__episode_content.json",
            kb.episode_path(project_id, "season_001", "episode_001") / "episode_summary.json",
            kb.episode_path(project_id, "season_001", "episode_001") / "episode_transcript.json",
            kb.chunks_root_path(project_id, "season_001", "episode_001") / "chunk_0001.json",
            kb.chunks_root_path(project_id, "season_001", "episode_001") / "preview__chunk_0002.json",
        ]
        for path in regenerable_paths:
            kb.write_json(path, {"ok": True})

        protected_paths = [
            paths.materials / "source.mp4",
            paths.output / "character_cards" / "export.json",
            kb.character_card_json_path(project_id, "official_card"),
            kb.preview_character_card_json_path(project_id),
            kb.root_path(project_id) / "facts.json",
            kb.root_path(project_id) / "seasons" / "season_001" / "episodes" / "episode_001" / "notes.txt",
        ]
        for path in protected_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("protected", encoding="utf-8")

        dry_run = kb.clean_regenerable_extraction_artifacts(project_id, dry_run=True)
        assert set(dry_run["deleted_paths"]) == {
            path.relative_to(paths.knowledge_base).as_posix() for path in regenerable_paths
        }
        assert all(path.exists() for path in regenerable_paths)

        result = kb.clean_regenerable_extraction_artifacts(project_id)
        assert set(result["deleted_paths"]) == set(dry_run["deleted_paths"])
        assert not any(path.exists() for path in regenerable_paths)
        assert all(path.exists() for path in protected_paths)
        assert result["warnings"] == []


def _assert_stale_marking_only_updates_compiled_official_cards() -> None:
    project_id = "validation-stale-cards"
    with _isolated_project_tree(project_id):
        save_card(
            CharacterCard(
                project_id=project_id,
                card_id="official_compiled",
                card_kind=CharacterCardKind.OFFICIAL,
                compile_status=CharacterCardStatus.COMPILED,
            )
        )
        save_card(
            CharacterCard(
                project_id=project_id,
                card_id="official_draft",
                card_kind=CharacterCardKind.OFFICIAL,
                compile_status=CharacterCardStatus.DRAFT,
            )
        )
        kb.write_json(
            kb.character_card_json_path(project_id, "template_compiled"),
            CharacterCard(
                project_id=project_id,
                card_id="template_compiled",
                card_kind=CharacterCardKind.TEMPLATE,
                compile_status=CharacterCardStatus.COMPILED,
            ).model_dump(mode="json"),
        )

        stale_card_ids = mark_compiled_official_cards_stale(
            project_id,
            reason="formal_extraction_updated",
        )
        assert stale_card_ids == ["official_compiled"]

        official_compiled = load_card(project_id, "official_compiled")
        official_draft = load_card(project_id, "official_draft")
        template_compiled = load_card(project_id, "template_compiled")

        assert official_compiled.compile_status == CharacterCardStatus.STALE
        assert "formal_extraction_updated" in official_compiled.quality.warnings
        assert official_draft.compile_status == CharacterCardStatus.DRAFT
        assert template_compiled.compile_status == CharacterCardStatus.COMPILED


def main() -> None:
    _assert_fast_concurrency_bounds()
    _assert_formal_json_retry_success_on_third_attempt()
    _assert_formal_json_retry_fails_after_three_attempts()
    _assert_formal_json_output_limit_stops_without_retry()
    _assert_fast_episode_and_season_skip_without_inputs()
    _assert_full_extraction_modes_stop_before_completion_without_chunks()
    _assert_run_artifact_filtering()
    _assert_clean_regenerable_artifacts_scope()
    _assert_stale_marking_only_updates_compiled_official_cards()
    print("formal extraction workflow validation passed")


if __name__ == "__main__":
    main()
