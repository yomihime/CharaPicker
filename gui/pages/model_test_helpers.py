from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from utils.ai_model_middleware import ModelMiddlewareError
from utils.i18n import t


LOCALE_LANGUAGE_HINTS = {
    "zh_CN": "Simplified Chinese",
    "zh_TW": "Traditional Chinese",
    "en_US": "English",
    "ja_JP": "Japanese",
}


def token_usage_log_fields(metadata: dict) -> tuple[int | None, int | None, int | None]:
    usage = metadata.get("token_usage")
    if not isinstance(usage, dict):
        return (None, None, None)
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None
    total_tokens = usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else None
    return (prompt_tokens, completion_tokens, total_tokens)


def token_usage_from_metadata(metadata: dict) -> dict[str, int]:
    usage = metadata.get("token_usage")
    if not isinstance(usage, dict):
        return {}
    normalized: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            normalized[key] = value
    return normalized


def format_token_usage_line(token_usage: dict[str, int]) -> str:
    prompt_tokens = token_usage.get("prompt_tokens")
    completion_tokens = token_usage.get("completion_tokens")
    total_tokens = token_usage.get("total_tokens")
    if not any(isinstance(value, int) for value in (prompt_tokens, completion_tokens, total_tokens)):
        return t("model.cloud.test.tokenUsage.empty")
    return t(
        "model.cloud.test.tokenUsage",
        prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else "-",
        completion_tokens=completion_tokens if isinstance(completion_tokens, int) else "-",
        total_tokens=total_tokens if isinstance(total_tokens, int) else "-",
    )


def build_data_url(asset_path: Path, default_mime: str) -> str:
    if not asset_path.exists():
        raise ModelMiddlewareError(f"Test asset does not exist: {asset_path}")
    mime_type, _ = mimetypes.guess_type(asset_path.name)
    mime_type = mime_type or default_mime
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def response_language_name(locale: str) -> str:
    return LOCALE_LANGUAGE_HINTS.get(locale, LOCALE_LANGUAGE_HINTS["zh_CN"])


def response_language_instruction(locale: str) -> str:
    return f"Respond in {response_language_name(locale)}."


def join_failed_items(items: list[str], locale: str) -> str:
    if not items:
        return ""
    if locale.startswith("en"):
        return ", ".join(items)
    if locale.startswith("ja"):
        return "、".join(items)
    return "、".join(items)
