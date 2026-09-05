from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


QQ_CHAT_EXPORTER_MARKER = "[QQChatExporter"
QQ_CHAT_EXPORT_TITLE = "QQ聊天记录导出文件"
QQ_CHAT_PARSER_VERSION = 1
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
    if path.suffix.lower() not in {".txt", ".md"}:
        return False
    try:
        with path.open("rb") as source:
            raw = source.read(CHAT_LOG_DETECT_BYTES)
    except OSError:
        return False
    for encoding in CHAT_LOG_ENCODINGS:
        try:
            return looks_like_qq_chat_export(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return False


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
