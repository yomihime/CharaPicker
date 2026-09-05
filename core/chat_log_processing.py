from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.chat_log_parser import ChatMessage
from core.models import (
    ChatEpistemicStatus,
    ChatObservation,
    ChatObservationType,
)


CHAT_SESSION_GAP_SECONDS = 2 * 60 * 60
CHAT_PREVIEW_WINDOW_COUNT = 3
ATTACHMENT_ONLY_PATTERN = re.compile(
    r"^(?:\[(?:图片|文件|视频|语音|音频|表情|动画表情|附件|转发消息)\]\s*)+$"
)
PII_PATTERNS = (
    (re.compile(r"(?<![\w.-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"), "[邮箱]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号]"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[身份证号]"),
    (re.compile(r"(?<!\d)(?:\d[ -]?){15,19}(?!\d)"), "[长号码]"),
    (re.compile(r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"), "[IP地址]"),
)


@dataclass(frozen=True, slots=True)
class ChatSession:
    index: int
    messages: list[ChatMessage]


@dataclass(frozen=True, slots=True)
class ChatModelView:
    text: str
    messages: list[ChatMessage]
    participant_aliases: dict[str, str]
    participant_names: dict[str, str]
    represented_message_count: int
    redaction_count: int
    session_count: int
    sampled: bool = False


@dataclass(frozen=True, slots=True)
class ChatIndexStats:
    message_count: int
    participant_count: int
    active_days: int
    attachment_only_count: int
    system_message_count: int
    recalled_message_count: int
    time_start: str
    time_end: str

    @property
    def one_sided(self) -> bool:
        return self.participant_count < 2


def build_chat_index_stats(messages: list[ChatMessage]) -> ChatIndexStats:
    days = {message.timestamp[:10] for message in messages if _timestamp(message) is not None}
    participants = {
        message.participant_id
        for message in messages
        if message.participant_id and not message.system
    }
    return ChatIndexStats(
        message_count=len(messages),
        participant_count=len(participants),
        active_days=len(days),
        attachment_only_count=sum(is_attachment_only(message) for message in messages),
        system_message_count=sum(message.system for message in messages),
        recalled_message_count=sum(message.recalled for message in messages),
        time_start=messages[0].timestamp if messages else "",
        time_end=messages[-1].timestamp if messages else "",
    )


def build_chat_sessions(
    messages: list[ChatMessage],
    *,
    gap_seconds: int = CHAT_SESSION_GAP_SECONDS,
) -> list[ChatSession]:
    sessions: list[ChatSession] = []
    current: list[ChatMessage] = []
    previous_time: datetime | None = None
    for message in messages:
        current_time = _timestamp(message)
        should_split = bool(
            current
            and current_time is not None
            and previous_time is not None
            and (current_time - previous_time).total_seconds() > gap_seconds
        )
        if should_split:
            sessions.append(ChatSession(index=len(sessions) + 1, messages=current))
            current = []
        current.append(message)
        if current_time is not None:
            previous_time = current_time
    if current:
        sessions.append(ChatSession(index=len(sessions) + 1, messages=current))
    return sessions


def build_chat_model_views(
    messages: list[ChatMessage],
    *,
    max_chars: int,
) -> list[ChatModelView]:
    aliases, names = _participant_maps(messages)
    reply_refs = _reply_reference_map(messages)
    sessions = build_chat_sessions(messages)
    views: list[ChatModelView] = []
    current_messages: list[ChatMessage] = []
    current_session_count = 0
    current_chars = 0

    def append_view(group: list[ChatMessage], session_count: int) -> None:
        if not group:
            return
        text, redactions = render_compact_chat_messages(
            group,
            participant_aliases=aliases,
            reply_refs=reply_refs,
        )
        views.append(
            ChatModelView(
                text=text,
                messages=list(group),
                participant_aliases=aliases,
                participant_names=names,
                represented_message_count=len(group),
                redaction_count=redactions,
                session_count=max(1, session_count),
            )
        )

    for session in sessions:
        session_groups = _split_message_group(
            session.messages,
            max_chars=max_chars,
            aliases=aliases,
            reply_refs=reply_refs,
        )
        for position, group in enumerate(session_groups):
            group_text, _ = render_compact_chat_messages(
                group,
                participant_aliases=aliases,
                reply_refs=reply_refs,
            )
            group_chars = len(group_text) + (1 if current_messages else 0)
            if current_messages and current_chars + group_chars > max_chars:
                append_view(current_messages, current_session_count)
                current_messages = []
                current_session_count = 0
                current_chars = 0
            current_messages.extend(group)
            current_chars += len(group_text) + (1 if current_chars else 0)
            if position == 0:
                current_session_count += 1
    append_view(current_messages, current_session_count)
    return views


def build_preview_chat_view(
    messages: list[ChatMessage],
    *,
    max_chars: int,
) -> ChatModelView:
    full_views = build_chat_model_views(messages, max_chars=max(800, max_chars // 3))
    if not full_views:
        raise ValueError("chat log does not contain previewable messages")
    selected_indexes = _stratified_indexes(len(full_views), CHAT_PREVIEW_WINDOW_COUNT)
    selected = [full_views[index] for index in selected_indexes]
    budget_each = max(300, max_chars // max(1, len(selected)))
    aliases, names = _participant_maps(messages)
    reply_refs = _reply_reference_map(messages)
    output_parts: list[str] = []
    output_messages: list[ChatMessage] = []
    redaction_count = 0
    for window_index, view in enumerate(selected, start=1):
        sampled_messages = _centered_message_sample(
            view.messages,
            max_chars=budget_each,
            aliases=aliases,
            reply_refs=reply_refs,
        )
        rendered, redactions = render_compact_chat_messages(
            sampled_messages,
            participant_aliases=aliases,
            reply_refs=reply_refs,
        )
        output_parts.append(
            f"[SAMPLED_WINDOW {window_index}/{len(selected)} "
            f"messages={sampled_messages[0].message_ref}-{sampled_messages[-1].message_ref}]\n{rendered}"
        )
        output_messages.extend(sampled_messages)
        redaction_count += redactions
    return ChatModelView(
        text="\n\n".join(output_parts),
        messages=output_messages,
        participant_aliases=aliases,
        participant_names=names,
        represented_message_count=len(output_messages),
        redaction_count=redaction_count,
        session_count=sum(view.session_count for view in selected),
        sampled=len(full_views) > len(selected),
    )


def render_compact_chat_messages(
    messages: list[ChatMessage],
    *,
    participant_aliases: dict[str, str],
    reply_refs: dict[str, str] | None = None,
) -> tuple[str, int]:
    reply_refs = reply_refs or {}
    lines: list[str] = []
    last_day = ""
    redaction_count = 0
    index = 0
    while index < len(messages):
        message = messages[index]
        day, clock = _date_and_clock(message.timestamp)
        if day and day != last_day:
            lines.append(f"[DATE {day}]")
            last_day = day
        alias = (
            "SYSTEM"
            if message.system
            else participant_aliases.get(message.participant_id, "P?")
        )
        if is_attachment_only(message):
            end = index + 1
            while end < len(messages) and _same_attachment_run(message, messages[end]):
                end += 1
            last = messages[end - 1]
            ref = (
                message.message_ref
                if end - index == 1
                else f"{message.message_ref}-{last.message_ref}"
            )
            lines.append(
                f"[{ref}|{clock}] {alias}: {message.content}"
                + (f" ×{end - index}" if end - index > 1 else "")
            )
            index = end
            continue
        content, count = redact_chat_text(message.content)
        redaction_count += count
        reply = reply_refs.get(message.reply_to_id, "")
        reply_suffix = f" reply={reply}" if reply else ""
        status = " recalled" if message.recalled else ""
        lines.append(
            f"[{message.message_ref}|{clock}{reply_suffix}{status}] {alias}: {content}"
        )
        index += 1
    return "\n".join(lines), redaction_count


def redact_chat_text(text: str) -> tuple[str, int]:
    output = text
    count = 0
    for pattern, replacement in PII_PATTERNS:
        output, replacements = pattern.subn(replacement, output)
        count += replacements
    return output, count


def normalize_chat_observations(
    payload: dict[str, Any],
    messages: list[ChatMessage],
    *,
    participant_aliases: dict[str, str] | None = None,
    participant_names: dict[str, str] | None = None,
) -> list[ChatObservation]:
    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list):
        return []
    aliases, names = _participant_maps(messages)
    if participant_aliases:
        aliases = dict(participant_aliases)
    if participant_names:
        names = dict(participant_names)
    name_by_alias = {alias: names[participant_id] for participant_id, alias in aliases.items()}
    participant_by_alias = {alias: participant_id for participant_id, alias in aliases.items()}
    messages_by_ref = {message.message_ref: message for message in messages}
    one_sided = len(aliases) < 2
    output: list[ChatObservation] = []
    for raw in raw_observations:
        if not isinstance(raw, dict):
            continue
        statement = str(raw.get("statement", "")).strip()
        if not statement:
            continue
        refs = _valid_refs(raw.get("message_refs"), messages_by_ref)
        context_refs = _valid_refs(raw.get("context_message_refs"), messages_by_ref)
        if not refs:
            continue
        alias = str(raw.get("participant_id", "")).strip()
        if alias not in participant_by_alias:
            referenced_participants = {
                messages_by_ref[ref].participant_id for ref in refs if ref in messages_by_ref
            }
            if len(referenced_participants) != 1:
                continue
            participant_id = next(iter(referenced_participants))
            alias = aliases.get(participant_id, "")
        participant_id = participant_by_alias.get(alias, "")
        if not participant_id:
            continue
        try:
            observation_type = ChatObservationType(str(raw.get("observation_type", "")))
            epistemic_status = ChatEpistemicStatus(
                str(raw.get("epistemic_status", ChatEpistemicStatus.DIRECT_OBSERVATION.value))
            )
        except ValueError:
            continue
        if one_sided and observation_type in {
            ChatObservationType.INTERACTION_SIGNAL,
            ChatObservationType.RELATIONSHIP_SIGNAL,
        }:
            continue
        confidence_value = raw.get("confidence", 0.5)
        try:
            confidence = min(1.0, max(0.0, float(confidence_value)))
        except (TypeError, ValueError):
            confidence = 0.5
        ref_messages = [messages_by_ref[ref] for ref in refs]
        observation_key = "|".join(
            [participant_id, observation_type.value, statement, *refs]
        )
        output.append(
            ChatObservation(
                observation_id=f"chatobs_{hashlib.sha256(observation_key.encode('utf-8')).hexdigest()[:16]}",
                participant_id=participant_id,
                participant_name=name_by_alias.get(alias, ""),
                observation_type=observation_type,
                statement=statement[:1000],
                epistemic_status=epistemic_status,
                message_refs=refs,
                context_message_refs=context_refs,
                time_start=ref_messages[0].timestamp,
                time_end=ref_messages[-1].timestamp,
                confidence=confidence,
                counter_evidence_refs=_valid_refs(
                    raw.get("counter_evidence_refs"), messages_by_ref
                ),
            )
        )
    return output


def project_chat_observations(
    observations: list[ChatObservation],
) -> dict[str, list[str]]:
    output = {
        "targets": [],
        "facts": [],
        "behavior_traits": [],
        "dialogue_style": [],
        "relationship_interactions": [],
        "conflicts": [],
        "character_state_changes": [],
        "evidence_refs": [],
    }
    for observation in observations:
        name = observation.participant_name or observation.participant_id
        refs = ",".join(observation.message_refs)
        value = f"{name}: {observation.statement}（聊天证据 {refs}）"
        output["targets"].append(name)
        output["evidence_refs"].extend(observation.message_refs)
        if observation.observation_type == ChatObservationType.UTTERANCE_STYLE:
            output["dialogue_style"].append(value)
        elif observation.observation_type == ChatObservationType.BEHAVIOR_SIGNAL:
            output["behavior_traits"].append(f"{name} 的行为信号（非稳定特质）: {observation.statement}（{refs}）")
        elif observation.observation_type in {
            ChatObservationType.INTERACTION_SIGNAL,
            ChatObservationType.RELATIONSHIP_SIGNAL,
        }:
            output["relationship_interactions"].append(value)
        elif observation.observation_type == ChatObservationType.CONFLICT_SIGNAL:
            output["conflicts"].append(value)
        elif observation.observation_type == ChatObservationType.STATE_SIGNAL:
            output["character_state_changes"].append(value)
        else:
            qualifier = {
                ChatEpistemicStatus.SELF_REPORTED: "自述",
                ChatEpistemicStatus.REPORTED_BY_OTHER: "他人陈述",
                ChatEpistemicStatus.INFERRED: "推断",
                ChatEpistemicStatus.UNCERTAIN: "未确认",
            }.get(observation.epistemic_status, "直接观察")
            output["facts"].append(f"{name}（{qualifier}）: {observation.statement}（{refs}）")
    return {key: list(dict.fromkeys(values)) for key, values in output.items()}


def is_attachment_only(message: ChatMessage) -> bool:
    return bool(ATTACHMENT_ONLY_PATTERN.fullmatch(message.content.strip()))


def _participant_maps(
    messages: list[ChatMessage],
) -> tuple[dict[str, str], dict[str, str]]:
    aliases: dict[str, str] = {}
    names: dict[str, str] = {}
    for message in messages:
        if message.system:
            continue
        participant_id = message.participant_id
        if not participant_id:
            continue
        if participant_id not in aliases:
            aliases[participant_id] = f"P{len(aliases) + 1}"
        names.setdefault(participant_id, message.sender)
    return aliases, names


def _reply_reference_map(messages: list[ChatMessage]) -> dict[str, str]:
    return {
        message.source_message_id: message.message_ref
        for message in messages
        if message.source_message_id
    }


def _split_message_group(
    messages: list[ChatMessage],
    *,
    max_chars: int,
    aliases: dict[str, str],
    reply_refs: dict[str, str],
) -> list[list[ChatMessage]]:
    groups: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    current_chars = 0
    for message in messages:
        rendered, _ = render_compact_chat_messages(
            [message],
            participant_aliases=aliases,
            reply_refs=reply_refs,
        )
        message_chars = len(rendered) + (1 if current else 0)
        if current and current_chars + message_chars > max_chars:
            groups.append(current)
            current = [message]
            current_chars = len(rendered)
        else:
            current.append(message)
            current_chars += message_chars
    if current:
        groups.append(current)
    return groups


def _centered_message_sample(
    messages: list[ChatMessage],
    *,
    max_chars: int,
    aliases: dict[str, str],
    reply_refs: dict[str, str],
) -> list[ChatMessage]:
    if not messages:
        return []
    selected: list[ChatMessage] = []
    center = len(messages) // 2
    order = sorted(range(len(messages)), key=lambda index: (abs(index - center), index))
    for index in order:
        candidate = sorted([*selected, messages[index]], key=lambda item: item.index)
        rendered, _ = render_compact_chat_messages(
            candidate,
            participant_aliases=aliases,
            reply_refs=reply_refs,
        )
        if selected and len(rendered) > max_chars:
            continue
        selected = candidate
    return selected or [messages[center]]


def _stratified_indexes(total: int, limit: int) -> list[int]:
    if total <= limit:
        return list(range(total))
    if limit <= 1:
        return [total // 2]
    indexes = {round(position * (total - 1) / (limit - 1)) for position in range(limit)}
    return sorted(indexes)


def _valid_refs(value: object, messages_by_ref: dict[str, ChatMessage]) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            ref
            for item in value
            if (ref := str(item).strip()) in messages_by_ref
        )
    )


def _same_attachment_run(first: ChatMessage, second: ChatMessage) -> bool:
    return (
        is_attachment_only(second)
        and first.participant_id == second.participant_id
        and first.content == second.content
        and first.timestamp[:10] == second.timestamp[:10]
    )


def _timestamp(message: ChatMessage) -> datetime | None:
    try:
        return datetime.strptime(message.timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _date_and_clock(value: str) -> tuple[str, str]:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "", value
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M")
