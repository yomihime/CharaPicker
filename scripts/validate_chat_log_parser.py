from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.chat_log_parser import (  # noqa: E402
    QQ_CHAT_PARSER_VERSION,
    is_qq_chat_export_path,
    looks_like_qq_chat_export,
    parse_qq_chat_export,
)
from core.extraction_ai import FormalExtractionJsonResult  # noqa: E402
from core.extraction_plan import ContentForm, ExtractionUnit, MaterialRef, MediaType  # noqa: E402
from core.extractor import Extractor  # noqa: E402
from core.models import ExtractionArtifactStage  # noqa: E402
from core.text_unit_handler import TextUnitHandler, TextUnitHandlerConfig  # noqa: E402
from utils.ai_model_middleware import ModelCallRequest  # noqa: E402


CHAT_FIXTURE = """[QQChatExporter V5 / https://example.invalid]
===============================================
           QQ聊天记录导出文件
===============================================
聊天名称: 验证会话
聊天类型: 私聊
消息总数: 3

甲:
时间: 2026-09-05 12:00:00
内容: 第一条消息


乙:
时间: 2026-09-05 12:01:00
内容: [图片:ABCDEF123456.jpg]
资源: 1 个文件
  - image: ABCDEF123456.jpg


甲:
时间: 2026-09-05 12:02:00
内容: 第三条
消息有第二行
"""


def _chat_unit() -> ExtractionUnit:
    material_ref = MaterialRef(
        material_id="material-chat-validation",
        relative_path="chat.txt",
        source_media_type=MediaType.TEXT,
        content_form=ContentForm.CHAT_LOG,
        metadata={"chat_format": "qq_chat_exporter", "chat_parser_version": 1},
    )
    return ExtractionUnit(
        unit_id="unit-chat-validation",
        episode_id="episode-chat-validation",
        media_type=MediaType.TEXT,
        content_form=ContentForm.CHAT_LOG,
        material_ref=material_ref,
        unit_kind="chat_log_text",
        handler_options={
            "chat_format": "qq_chat_exporter",
            "chat_parser_version": QQ_CHAT_PARSER_VERSION,
        },
    )


def _assert_parser() -> None:
    assert looks_like_qq_chat_export(CHAT_FIXTURE)
    document = parse_qq_chat_export(CHAT_FIXTURE)
    assert document.format_name == "qq_chat_exporter"
    assert document.metadata["聊天名称"] == "验证会话"
    assert len(document.messages) == 3
    assert document.messages[0].sender == "甲"
    assert document.messages[1].content == "[图片]"
    assert "ABCDEF" not in document.messages[1].content
    assert document.messages[1].has_resource_block is True
    assert document.messages[2].content == "第三条\n消息有第二行"
    assert [message.index for message in document.messages] == [1, 2, 3]
    assert all(
        left.end_offset <= right.start_offset
        for left, right in zip(document.messages[:-1], document.messages[1:], strict=True)
    )


def _assert_message_boundary_chunking() -> None:
    with TemporaryDirectory(prefix="charapicker-chat-parser-") as temp_dir:
        root = Path(temp_dir)
        path = root / "chat.txt"
        path.write_text(CHAT_FIXTURE, encoding="utf-8")
        assert is_qq_chat_export_path(path)
        unit = _chat_unit()
        handler = TextUnitHandler(
            TextUnitHandlerConfig(
                max_input_chars=70,
                max_chat_chunks_per_unit=10,
            )
        )
        parsed = handler.parse_material(path, unit_kind=unit.unit_kind)
        chunks, warnings = handler._prepare_chunks(parsed, chunk_limit=None)
        assert len(chunks) >= 2
        assert any("chat_log_split_into_chunks" in warning for warning in warnings)
        assert sum(len(chunk.chat_messages) for chunk in chunks) == 3
        assert all(chunk.chat_messages for chunk in chunks)
        assert "ABCDEF" not in "\n".join(chunk.text for chunk in chunks)
        assert chunks[0].start_offset == parsed.chat_messages[0].start_offset
        assert chunks[-1].end_offset == parsed.chat_messages[-1].end_offset

        plan = handler.plan_unit(source_root=root, unit=unit)
        assert plan.coverage_percent == 100.0
        limited = handler.plan_unit(source_root=root, unit=unit, chunk_limit=1)
        assert limited.coverage_percent < 100.0
        assert any("chat_log_chunk_limit_reached" in warning for warning in limited.warnings)

        requests: list[ModelCallRequest] = []

        def fake_model(request: ModelCallRequest) -> FormalExtractionJsonResult:
            requests.append(request)
            return FormalExtractionJsonResult(
                payload={
                    "facts": ["甲发送了一条消息"],
                    "behavior_traits": [],
                    "dialogue_style": [],
                    "relationship_interactions": [],
                    "conflicts": [],
                    "character_state_changes": [],
                    "insight_summary": "聊天记录验证",
                    "evidence_refs": [],
                },
                content="{}",
                token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                requested_output_tokens=1024,
                finish_reason="stop",
                estimated_context_tokens=20,
                model_metadata={"validation": True},
            )

        execution_handler = TextUnitHandler(
            TextUnitHandlerConfig(max_input_chars=70, max_output_tokens=1024),
            model_call=fake_model,
        )
        result = execution_handler.execute(
            source_root=root,
            unit=unit,
            season_id="season_materials",
            extraction_stage=ExtractionArtifactStage.PREVIEW,
            extraction_run_id="",
            run_type="preview_trial",
            backend="openai_compatible",
            model_name="validation-model",
            base_url="https://example.invalid/v1",
            api_key="validation-key",
            chunk_limit=1,
        )
        assert requests[0].metadata["chat_format"] == "qq_chat_exporter"
        assert result.chunks[0].source_counts["chat_messages"] > 0
        locator = result.chunks[0].source_trace["evidence_refs"][0]["locator"]
        assert locator["message_index_start"] == 1
        assert locator["message_time_start"] == "2026-09-05 12:00:00"

        legacy_trace = deepcopy(result.chunks[0].source_trace)
        legacy_trace["material_refs"][0]["content_form"] = "novel"
        legacy_chunk = result.chunks[0].model_copy(update={"source_trace": legacy_trace})
        extractor = Extractor()
        assert not extractor._chunk_source_matches(
            legacy_chunk,
            expected_source_path=unit.material_ref.relative_path,
            expected_source_trace=extractor._source_trace_for_unit(unit).model_dump(mode="json"),
        )
        stale_parser_trace = deepcopy(result.chunks[0].source_trace)
        stale_parser_trace["material_refs"][0]["metadata"]["chat_parser_version"] = 0
        stale_parser_chunk = result.chunks[0].model_copy(
            update={"source_trace": stale_parser_trace}
        )
        assert not extractor._chunk_source_matches(
            stale_parser_chunk,
            expected_source_path=unit.material_ref.relative_path,
            expected_source_trace=extractor._source_trace_for_unit(unit).model_dump(mode="json"),
        )


def main() -> None:
    _assert_parser()
    _assert_message_boundary_chunking()
    print("chat log parser validation passed")


if __name__ == "__main__":
    main()
