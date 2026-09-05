from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.chat_log_parser import (  # noqa: E402
    QQ_CHAT_PARSER_VERSION,
    is_qq_chat_export_path,
    looks_like_qq_chat_export,
    parse_chat_export,
    parse_qq_chat_export,
)
from core.chat_log_processing import (  # noqa: E402
    build_preview_chat_view,
    normalize_chat_observations,
    render_compact_chat_messages,
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

JSON_MESSAGES = [
    {
        "id": "101",
        "timestamp": 1788580800000,
        "time": "2026-09-05 12:00:00",
        "sender": {"uid": "u-001", "name": "真实甲"},
        "type": "text",
        "content": {"text": "联系邮箱 a@example.com", "elements": [], "resources": []},
        "recalled": False,
        "system": False,
    },
    {
        "id": "102",
        "timestamp": 1788580860000,
        "time": "2026-09-05 12:01:00",
        "sender": {"uid": "u-002", "name": "真实乙"},
        "type": "mixed",
        "content": {
            "text": "收到",
            "elements": [{"type": "reply", "data": {"referencedMessageId": "101"}}],
            "resources": [],
        },
        "recalled": False,
        "system": False,
    },
]

JSON_FIXTURE = json.dumps(
    {
        "metadata": {"name": "QQChatExporter", "version": "5"},
        "chatInfo": {"name": "验证会话", "type": "private"},
        "statistics": {"totalMessages": 2},
        "messages": JSON_MESSAGES,
    },
    ensure_ascii=False,
)
JSONL_FIXTURE = "\n".join(json.dumps(item, ensure_ascii=False) for item in JSON_MESSAGES)


def _chat_unit() -> ExtractionUnit:
    material_ref = MaterialRef(
        material_id="material-chat-validation",
        relative_path="chat.txt",
        source_media_type=MediaType.TEXT,
        content_form=ContentForm.CHAT_LOG,
        metadata={
            "chat_format": "qq_chat_exporter",
            "chat_parser_version": QQ_CHAT_PARSER_VERSION,
        },
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

    json_document = parse_chat_export(JSON_FIXTURE, suffix=".json")
    assert json_document.format_name == "qq_chat_exporter_json"
    assert len(json_document.messages) == 2
    assert json_document.messages[1].reply_to_id == "101"
    assert json_document.messages[0].participant_id != "u-001"

    jsonl_document = parse_chat_export(JSONL_FIXTURE, suffix=".jsonl")
    assert jsonl_document.format_name == "qq_chat_exporter_jsonl"
    assert len(jsonl_document.messages) == 2
    aliases = {
        message.participant_id: f"P{index}"
        for index, message in enumerate(jsonl_document.messages, start=1)
    }
    rendered, redactions = render_compact_chat_messages(
        jsonl_document.messages,
        participant_aliases=aliases,
        reply_refs={"101": "m000001", "102": "m000002"},
    )
    assert "真实甲" not in rendered
    assert "a@example.com" not in rendered
    assert "[邮箱]" in rendered
    assert "reply=m000001" in rendered
    assert redactions == 1

    preview_source = jsonl_document.messages * 80
    preview_source = [
        replace(
            message,
            index=index,
            source_message_id=str(100 + index),
        )
        for index, message in enumerate(preview_source, start=1)
    ]
    preview = build_preview_chat_view(preview_source, max_chars=1200)
    assert preview.sampled
    assert "SAMPLED_WINDOW 1/3" in preview.text
    assert "SAMPLED_WINDOW 3/3" in preview.text

    one_sided = [json_document.messages[0]]
    rejected = normalize_chat_observations(
        {
            "observations": [
                {
                    "participant_id": "P1",
                    "observation_type": "relationship_signal",
                    "statement": "关系结论",
                    "epistemic_status": "inferred",
                    "message_refs": ["m000001"],
                }
            ]
        },
        one_sided,
    )
    assert rejected == []
    global_aliases = {
        message.participant_id: f"P{index}"
        for index, message in enumerate(json_document.messages, start=1)
    }
    accepted = normalize_chat_observations(
        {
            "observations": [
                {
                    "participant_id": "P1",
                    "observation_type": "relationship_signal",
                    "statement": "仅作为跨参与者聊天中的局部关系信号",
                    "epistemic_status": "inferred",
                    "message_refs": ["m000001"],
                }
            ]
        },
        one_sided,
        participant_aliases=global_aliases,
        participant_names={
            message.participant_id: message.sender for message in json_document.messages
        },
    )
    assert len(accepted) == 1


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
                    "observations": [
                        {
                            "participant_id": "P1",
                            "observation_type": "utterance_style",
                            "statement": "使用简短陈述",
                            "epistemic_status": "direct_observation",
                            "message_refs": ["m000001"],
                            "context_message_refs": [],
                            "confidence": 0.8,
                            "counter_evidence_refs": [],
                        }
                    ],
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
        assert requests[0].purpose == "preview_chat_log_extraction"
        assert requests[0].metadata["chat_format"] == "qq_chat_exporter"
        assert result.chunks[0].source_counts["chat_messages"] > 0
        assert result.chunks[0].chat_observations
        assert result.chunks[0].dialogue_style
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

        with (
            patch.object(extractor, "merge_episode_content") as merge_episode,
            patch.object(extractor, "generate_episode_summary") as summarize_episode,
        ):
            ready, merge_usage = extractor._finalize_formal_episode_context(
                "validation-project",
                {"seasons": []},
                "season_materials",
                unit.episode_id,
                chunk_inputs=[{"chunk_id": result.chunks[0].chunk_id}],
                episode_chunks=result.chunks,
                previous_episode_id="",
                extraction_run_id="validation-run",
                backend="openai_compatible",
                model_name="validation-model",
                base_url="https://example.invalid/v1",
                api_key="validation-key",
                context_window_tokens=8_192,
            )
        assert ready is True
        assert merge_usage == {}
        merge_episode.assert_called_once()
        summarize_episode.assert_called_once()


def main() -> None:
    _assert_parser()
    _assert_message_boundary_chunking()
    print("chat log parser validation passed")


if __name__ == "__main__":
    main()
