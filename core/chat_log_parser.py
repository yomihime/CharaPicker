from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


QQ_CHAT_EXPORTER_MARKER = "[QQChatExporter"
QQ_CHAT_EXPORT_TITLE = "QQ聊天记录导出文件"
QQ_CHAT_PARSER_VERSION = 2
CHAT_LOG_DETECT_BYTES = 64 * 1024
CHAT_LOG_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")
MESSAGE_HEADER_PATTERN = re.compile(
    r"(?m)^(?P<sender>[^\r\n]{1,200}):\r?\n"
    r"时间:\s*(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\r?\n"
    r"内容:\s?"
)
RESOURCE_BLOCK_PATTERN = re.compile(r"\r?\n资源:\s*\d+\s*个文件(?:\r?\n|$)")
ATTACHMENT_PATTERN = re.compile(
    r"\[(?P<kind>图片|文件|视频|语音|音频|表情|动画表情)(?::[^\]]*)?\]"
)
HEADER_FIELD_PATTERN = re.compile(
    r"(?m)^(?P<key>聊天名称|聊天类型|导出时间|消息总数|时间范围):\s*(?P<value>.+?)\s*$"
)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    index: int
    sender: str
    timestamp: str
    content: str
    start_offset: int
    end_offset: int
    has_resource_block: bool = False
    participant_id: str = ""
    source_message_id: str = ""
    message_type: str = "text"
    reply_to_id: str = ""
    system: bool = False
    recalled: bool = False
    attachment_types: tuple[str, ...] = ()

    @property
    def message_ref(self) -> str:
        return f"m{self.index:06d}"


@dataclass(frozen=True, slots=True)
class ChatLogDocument:
    format_name: str
    messages: list[ChatMessage]
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def looks_like_qq_chat_export(text: str) -> bool:
    return (
        QQ_CHAT_EXPORTER_MARKER in text[:4096]
        and QQ_CHAT_EXPORT_TITLE in text[:8192]
        and MESSAGE_HEADER_PATTERN.search(text) is not None
    )


def is_qq_chat_export_path(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in {".txt", ".md", ".json", ".jsonl"}:
        return False
    try:
        with path.open("rb") as source:
            raw = source.read(CHAT_LOG_DETECT_BYTES)
    except OSError:
        return False
    for encoding in CHAT_LOG_ENCODINGS:
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if suffix in {".txt", ".md"}:
            return looks_like_qq_chat_export(decoded)
        if suffix == ".jsonl":
            return looks_like_qq_chat_export_jsonl(decoded)
        return looks_like_qq_chat_export_json_text(decoded)
    return False


def looks_like_qq_chat_export_json_text(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        compact_prefix = text[:CHAT_LOG_DETECT_BYTES]
        return (
            '"metadata"' in compact_prefix
            and re.search(r"QQ\s*Chat\s*Exporter", compact_prefix, re.IGNORECASE)
            is not None
            and '"messages"' in compact_prefix
        )
    return looks_like_qq_chat_export_json(payload)


def looks_like_qq_chat_export_json(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    metadata = payload.get("metadata")
    name = metadata.get("name", "") if isinstance(metadata, dict) else ""
    normalized_name = re.sub(r"[^a-z]", "", name.casefold()) if isinstance(name, str) else ""
    messages = payload.get("messages")
    return (
        "qqchatexporter" in normalized_name
        and isinstance(messages, list)
        and (not messages or isinstance(messages[0], dict))
    )


def looks_like_qq_chat_export_jsonl(text: str) -> bool:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return False
    try:
        payload = json.loads(first_line)
    except json.JSONDecodeError:
        return False
    return _looks_like_qce_message(payload)


def parse_chat_export(text: str, *, suffix: str = ".txt") -> ChatLogDocument:
    normalized_suffix = suffix.lower()
    if normalized_suffix == ".json":
        return parse_qq_chat_export_json(text)
    if normalized_suffix == ".jsonl":
        return parse_qq_chat_export_jsonl(text)
    return parse_qq_chat_export(text)


def parse_qq_chat_export(text: str) -> ChatLogDocument:
    if not looks_like_qq_chat_export(text):
        raise ValueError("text is not a supported QQChatExporter document")
    matches = list(MESSAGE_HEADER_PATTERN.finditer(text))
    messages: list[ChatMessage] = []
    for index, match in enumerate(matches, start=1):
        end_offset = matches[index].start() if index < len(matches) else len(text)
        raw_content = text[match.end() : end_offset].strip("\r\n")
        resource_match = RESOURCE_BLOCK_PATTERN.search(raw_content)
        has_resource_block = resource_match is not None
        if resource_match is not None:
            raw_content = raw_content[: resource_match.start()].rstrip()
        normalized_content = _normalize_message_content(raw_content)
        if not normalized_content and has_resource_block:
            normalized_content = "[附件]"
        messages.append(
            ChatMessage(
                index=index,
                sender=match.group("sender").strip(),
                timestamp=match.group("timestamp"),
                content=normalized_content,
                start_offset=match.start(),
                end_offset=end_offset,
                has_resource_block=has_resource_block,
                participant_id=_participant_id(match.group("sender").strip()),
                source_message_id=f"txt-{index}",
                attachment_types=_attachment_types(normalized_content),
            )
        )
    if not messages:
        raise ValueError("QQChatExporter document does not contain messages")
    metadata = {
        match.group("key"): match.group("value").strip()
        for match in HEADER_FIELD_PATTERN.finditer(text[: matches[0].start()])
    }
    warnings: list[str] = []
    declared_count = metadata.get("消息总数", "")
    if declared_count.isdigit() and int(declared_count) != len(messages):
        warnings.append(
            f"chat_message_count_mismatch:declared={declared_count}:parsed={len(messages)}"
        )
    return ChatLogDocument(
        format_name="qq_chat_exporter",
        messages=messages,
        metadata=metadata,
        warnings=warnings,
    )


def parse_qq_chat_export_json(text: str) -> ChatLogDocument:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("QQChatExporter JSON is invalid") from exc
    if not looks_like_qq_chat_export_json(payload):
        raise ValueError("JSON is not a supported QQChatExporter document")
    assert isinstance(payload, dict)
    raw_messages = payload.get("messages", [])
    assert isinstance(raw_messages, list)
    messages = [
        _chat_message_from_json(item, index=index, start_offset=index - 1, end_offset=index)
        for index, item in enumerate(raw_messages, start=1)
        if isinstance(item, dict)
    ]
    metadata = _json_metadata(payload)
    warnings = _message_count_warnings(payload, len(messages))
    return ChatLogDocument(
        format_name="qq_chat_exporter_json",
        messages=messages,
        metadata=metadata,
        warnings=warnings,
    )


def parse_qq_chat_export_jsonl(text: str) -> ChatLogDocument:
    messages: list[ChatMessage] = []
    warnings: list[str] = []
    offset = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        end_offset = offset + len(line)
        if not stripped:
            offset = end_offset
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            warnings.append(f"chat_jsonl_line_invalid:line={line_number}")
            offset = end_offset
            continue
        if not _looks_like_qce_message(payload):
            warnings.append(f"chat_jsonl_line_unsupported:line={line_number}")
            offset = end_offset
            continue
        messages.append(
            _chat_message_from_json(
                payload,
                index=len(messages) + 1,
                start_offset=offset,
                end_offset=end_offset,
            )
        )
        offset = end_offset
    if not messages:
        raise ValueError("QQChatExporter JSONL does not contain supported messages")
    return ChatLogDocument(
        format_name="qq_chat_exporter_jsonl",
        messages=messages,
        warnings=warnings,
    )


def render_chat_message(message: ChatMessage) -> str:
    content = message.content or "[空消息]"
    return f"[{message.timestamp}] {message.sender}: {content}"


def render_chat_messages(messages: list[ChatMessage]) -> str:
    return "\n".join(render_chat_message(message) for message in messages)


def _normalize_message_content(content: str) -> str:
    normalized = ATTACHMENT_PATTERN.sub(
        lambda match: f"[{match.group('kind')}]",
        content,
    )
    return normalized.strip()


def _chat_message_from_json(
    payload: dict[str, Any],
    *,
    index: int,
    start_offset: int,
    end_offset: int,
) -> ChatMessage:
    sender_payload = payload.get("sender")
    sender_payload = sender_payload if isinstance(sender_payload, dict) else {}
    sender = _first_string(
        sender_payload.get("groupCard"),
        sender_payload.get("remark"),
        sender_payload.get("name"),
        sender_payload.get("nickname"),
        "unknown",
    )
    sender_key = _first_string(
        sender_payload.get("uid"),
        sender_payload.get("uin"),
        sender,
    )
    content_payload = payload.get("content")
    if isinstance(content_payload, dict):
        content = _first_string(content_payload.get("text"))
        elements = content_payload.get("elements")
        resources = content_payload.get("resources")
    else:
        content = _first_string(content_payload)
        elements = []
        resources = []
    elements = elements if isinstance(elements, list) else []
    resources = resources if isinstance(resources, list) else []
    attachment_types = _json_attachment_types(elements, resources)
    if not content and attachment_types:
        content = " ".join(f"[{kind}]" for kind in attachment_types)
    content = _normalize_message_content(content) or "[空消息]"
    reply_to_id = _json_reply_to_id(elements)
    source_message_id = _first_string(payload.get("id"), payload.get("seq"), str(index))
    timestamp = _json_timestamp(payload)
    return ChatMessage(
        index=index,
        sender=sender,
        timestamp=timestamp,
        content=content,
        start_offset=start_offset,
        end_offset=end_offset,
        has_resource_block=bool(resources),
        participant_id=_participant_id(sender_key),
        source_message_id=source_message_id,
        message_type=_first_string(payload.get("type"), "text"),
        reply_to_id=reply_to_id,
        system=bool(payload.get("system")),
        recalled=bool(payload.get("recalled")),
        attachment_types=tuple(attachment_types),
    )


def _looks_like_qce_message(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("sender"), dict) and "content" in payload and (
        "time" in payload or "timestamp" in payload
    )


def _json_metadata(payload: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in ("name", "version"):
            value = metadata.get(key)
            if value is not None:
                output[key] = str(value)
    chat_info = payload.get("chatInfo")
    if isinstance(chat_info, dict):
        for source_key, target_key in (("name", "聊天名称"), ("type", "聊天类型")):
            value = chat_info.get(source_key)
            if value is not None:
                output[target_key] = str(value)
    return output


def _message_count_warnings(payload: dict[str, Any], parsed_count: int) -> list[str]:
    statistics = payload.get("statistics")
    declared = statistics.get("totalMessages") if isinstance(statistics, dict) else None
    if isinstance(declared, int) and declared != parsed_count:
        return [f"chat_message_count_mismatch:declared={declared}:parsed={parsed_count}"]
    return []


def _json_timestamp(payload: dict[str, Any]) -> str:
    formatted = _first_string(payload.get("time"))
    if formatted:
        return formatted
    raw_timestamp = payload.get("timestamp")
    if isinstance(raw_timestamp, (int, float)):
        seconds = float(raw_timestamp)
        if seconds > 10_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            pass
    return "unknown-time"


def _json_attachment_types(elements: list[Any], resources: list[Any]) -> list[str]:
    mapping = {
        "image": "图片",
        "video": "视频",
        "audio": "语音",
        "file": "文件",
        "face": "表情",
        "market_face": "表情",
        "marketFace": "表情",
        "forward": "转发消息",
    }
    output: list[str] = []
    for item in [*elements, *resources]:
        if not isinstance(item, dict):
            continue
        kind = _first_string(item.get("type"))
        normalized = mapping.get(kind)
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def _json_reply_to_id(elements: list[Any]) -> str:
    for item in elements:
        if not isinstance(item, dict) or item.get("type") != "reply":
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        return _first_string(
            data.get("referencedMessageId"),
            data.get("replyMsgId"),
            data.get("messageId"),
            data.get("msgId"),
        )
    return ""


def _participant_id(value: str) -> str:
    digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:12]
    return f"participant_{digest}"


def _attachment_types(content: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group("kind") for match in ATTACHMENT_PATTERN.finditer(content)))


def _first_string(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""
