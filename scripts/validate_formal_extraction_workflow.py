from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.extraction_ai import FormalExtractionJsonError, call_formal_json_model  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.models import ExtractionMode, ProjectConfig  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest, ModelCallResult, ModelMessage  # noqa: E402


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
            return ModelCallResult(content="not json", metadata={"token_usage": {"total_tokens": 1}})
        return ModelCallResult(
            content='{"ok": true}',
            metadata={"token_usage": {"prompt_tokens": 1, "completion_tokens": 2}},
        )

    result = call_formal_json_model(request, call_model=fake_call)
    assert result.payload == {"ok": True}
    assert result.attempts == 3
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
        return
    raise AssertionError("expected FormalExtractionJsonError after three attempts")


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


def main() -> None:
    _assert_fast_concurrency_bounds()
    _assert_formal_json_retry_success_on_third_attempt()
    _assert_formal_json_retry_fails_after_three_attempts()
    _assert_fast_episode_and_season_skip_without_inputs()
    print("formal extraction workflow validation passed")


if __name__ == "__main__":
    main()
