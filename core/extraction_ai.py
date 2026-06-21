from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.extraction_context import estimate_context_tokens
from utils.ai_model_middleware import (
    ModelBackend,
    ModelCallError,
    ModelCallRequest,
    ModelCallResult,
    build_model_call_request,
    call_audio_model,
    call_image_model,
    call_text_model,
    call_video_model,
)


LOGGER = logging.getLogger(__name__)
FORMAL_JSON_PARSE_MAX_ATTEMPTS = 3
OUTPUT_LIMIT_FINISH_REASONS = {"length", "max_tokens"}
TOKEN_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


class FormalExtractionJsonError(ModelCallError):
    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        attempt_metadata: list[dict[str, Any]] | None = None,
        last_content: str = "",
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.attempt_metadata = attempt_metadata or []
        self.last_content = last_content


class FormalExtractionOutputTruncatedError(FormalExtractionJsonError):
    pass


@dataclass(frozen=True)
class FormalExtractionJsonResult:
    payload: dict[str, Any]
    content: str
    token_usage: dict[str, int] = field(default_factory=dict)
    requested_output_tokens: int | None = None
    finish_reason: str = ""
    output_truncated: bool = False
    estimated_context_tokens: int | None = None
    model_metadata: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1

    def artifact_metadata(self) -> dict[str, Any]:
        return {
            "token_usage": self.token_usage,
            "requested_output_tokens": self.requested_output_tokens,
            "finish_reason": self.finish_reason,
            "estimated_context_tokens": self.estimated_context_tokens,
            "model_metadata": self.model_metadata,
        }


def build_formal_text_json_request(
    *,
    purpose: str,
    backend: ModelBackend,
    model_name: str,
    variables: dict[str, Any],
    base_url: str = "",
    api_key: str = "",
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout_seconds: int = 240,
    metadata: dict[str, Any] | None = None,
) -> ModelCallRequest:
    request = build_model_call_request(
        purpose=purpose,
        backend=backend,
        model_name=model_name,
        variables=variables,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        metadata=metadata,
    )
    return request.model_copy(
        update={
            "timeout_seconds": timeout_seconds,
            "response_format": {"type": "json_object"},
        }
    )


def call_formal_text_json_model(
    request: ModelCallRequest,
    *,
    max_attempts: int = FORMAL_JSON_PARSE_MAX_ATTEMPTS,
    estimated_context_tokens: int | None = None,
) -> FormalExtractionJsonResult:
    return call_formal_json_model(
        request,
        call_model=call_text_model,
        max_attempts=max_attempts,
        estimated_context_tokens=estimated_context_tokens,
    )


def call_formal_image_json_model(
    request: ModelCallRequest,
    *,
    max_attempts: int = FORMAL_JSON_PARSE_MAX_ATTEMPTS,
    estimated_context_tokens: int | None = None,
) -> FormalExtractionJsonResult:
    return call_formal_json_model(
        request,
        call_model=call_image_model,
        max_attempts=max_attempts,
        estimated_context_tokens=estimated_context_tokens,
    )


def call_formal_audio_json_model(
    request: ModelCallRequest,
    *,
    max_attempts: int = FORMAL_JSON_PARSE_MAX_ATTEMPTS,
    estimated_context_tokens: int | None = None,
) -> FormalExtractionJsonResult:
    return call_formal_json_model(
        request,
        call_model=call_audio_model,
        max_attempts=max_attempts,
        estimated_context_tokens=estimated_context_tokens,
    )


def call_formal_video_json_model(
    request: ModelCallRequest,
    *,
    max_attempts: int = FORMAL_JSON_PARSE_MAX_ATTEMPTS,
    estimated_context_tokens: int | None = None,
) -> FormalExtractionJsonResult:
    return call_formal_json_model(
        request,
        call_model=call_video_model,
        max_attempts=max_attempts,
        estimated_context_tokens=estimated_context_tokens,
    )


def call_formal_json_model(
    request: ModelCallRequest,
    *,
    call_model: Callable[[ModelCallRequest], ModelCallResult],
    max_attempts: int = FORMAL_JSON_PARSE_MAX_ATTEMPTS,
    estimated_context_tokens: int | None = None,
) -> FormalExtractionJsonResult:
    attempts = max(1, max_attempts)
    attempt_metadata: list[dict[str, Any]] = []
    token_usage_total: dict[str, int] = {key: 0 for key in TOKEN_USAGE_KEYS}
    last_content = ""
    last_error = "model response is not a JSON object"
    prompt_estimate = estimated_context_tokens
    if prompt_estimate is None:
        prompt_estimate = estimate_context_tokens(_request_text_for_estimate(request))

    for attempt in range(1, attempts + 1):
        LOGGER.debug(
            "Formal extraction JSON model attempt started; purpose=%s attempt=%s/%s "
            "estimated_prompt_tokens=%s requested_output_tokens=%s",
            request.purpose,
            attempt,
            attempts,
            prompt_estimate,
            request.max_tokens,
        )
        result = call_model(request)
        content = result.content if isinstance(result.content, str) else ""
        last_content = content
        finish_reason = model_finish_reason(result)
        token_usage = normalized_token_usage(result)
        for key in TOKEN_USAGE_KEYS:
            token_usage_total[key] += token_usage.get(key, 0)
        metadata = _attempt_metadata(
            result,
            attempt=attempt,
            requested_output_tokens=request.max_tokens,
            estimated_context_tokens=prompt_estimate,
        )
        attempt_metadata.append(metadata)
        LOGGER.debug(
            "Formal extraction JSON model attempt received; purpose=%s attempt=%s/%s "
            "finish_reason=%s content_chars=%s token_usage=%s",
            request.purpose,
            attempt,
            attempts,
            finish_reason,
            len(content),
            token_usage,
        )

        if model_stopped_by_output_limit(result):
            LOGGER.warning(
                "Formal extraction JSON model response truncated; purpose=%s attempt=%s/%s "
                "finish_reason=%s content_chars=%s requested_output_tokens=%s",
                request.purpose,
                attempt,
                attempts,
                finish_reason,
                len(content),
                request.max_tokens,
            )
            raise FormalExtractionOutputTruncatedError(
                "formal extraction model response was truncated",
                attempts=attempt,
                attempt_metadata=attempt_metadata,
                last_content=content,
            )

        try:
            payload = extract_json_object(content)
        except ValueError as exc:
            last_error = str(exc)
            LOGGER.warning(
                "Formal extraction JSON parse failed; purpose=%s attempt=%s/%s "
                "finish_reason=%s content_chars=%s",
                request.purpose,
                attempt,
                attempts,
                finish_reason,
                len(content),
            )
            continue

        token_usage_total = _trim_empty_token_usage(token_usage_total)
        model_metadata = {
            "attempt_count": attempt,
            "attempts": attempt_metadata,
            "output_truncated": False,
            "token_usage_missing": not token_usage_total,
            "token_usage_incomplete": any(
                not item.get("token_usage") for item in attempt_metadata
            ),
            "successful_attempt_token_usage": token_usage,
            "estimated_prompt_tokens": prompt_estimate,
            "response_content_chars": len(content),
        }
        LOGGER.debug(
            "Formal extraction JSON parsed; purpose=%s attempt=%s/%s token_usage_total=%s "
            "response_content_chars=%s",
            request.purpose,
            attempt,
            attempts,
            token_usage_total,
            len(content),
        )
        return FormalExtractionJsonResult(
            payload=payload,
            content=content,
            token_usage=token_usage_total,
            requested_output_tokens=request.max_tokens,
            finish_reason=finish_reason,
            output_truncated=False,
            estimated_context_tokens=prompt_estimate,
            model_metadata=model_metadata,
            attempts=attempt,
        )

    raise FormalExtractionJsonError(
        f"formal extraction model response could not be parsed as JSON after "
        f"{attempts} attempts: {last_error}",
        attempts=attempts,
        attempt_metadata=attempt_metadata,
        last_content=last_content,
    )


def extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ValueError("empty model response")
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    candidates = list(extract_json_object_candidates(text))
    if candidates:
        return candidates[-1]
    raise ValueError("model response is not a JSON object")


def extract_json_object_candidates(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            candidates.append(payload)
    return candidates


def model_finish_reason(result: ModelCallResult) -> str:
    first_choice = model_first_choice(result)
    return str(first_choice.get("finish_reason") or "").strip().lower()


def model_stopped_by_output_limit(result: ModelCallResult) -> bool:
    return model_finish_reason(result) in OUTPUT_LIMIT_FINISH_REASONS


def model_first_choice(result: ModelCallResult) -> dict[str, Any]:
    raw = result.raw if isinstance(getattr(result, "raw", None), dict) else {}
    choices = raw.get("choices")
    if not isinstance(choices, list):
        output = raw.get("output")
        if isinstance(output, dict):
            choices = output.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(first_choice, dict):
        return {}
    return first_choice


def normalized_token_usage(result: ModelCallResult) -> dict[str, int]:
    token_usage = result.metadata.get("token_usage")
    if not isinstance(token_usage, dict):
        return {}
    return {
        key: value
        for key, value in token_usage.items()
        if key in TOKEN_USAGE_KEYS and isinstance(value, int)
    }


def total_token_usage(items: list[dict[str, int]]) -> dict[str, int]:
    totals = {key: 0 for key in TOKEN_USAGE_KEYS}
    for item in items:
        for key in TOKEN_USAGE_KEYS:
            totals[key] += item.get(key, 0)
    return _trim_empty_token_usage(totals)


def _attempt_metadata(
    result: ModelCallResult,
    *,
    attempt: int,
    requested_output_tokens: int | None,
    estimated_context_tokens: int | None,
) -> dict[str, Any]:
    content = result.content if isinstance(result.content, str) else ""
    token_usage = normalized_token_usage(result)
    output_truncated = model_stopped_by_output_limit(result)
    return {
        "attempt": attempt,
        "token_usage": token_usage,
        "token_usage_missing": not token_usage,
        "requested_output_tokens": requested_output_tokens,
        "finish_reason": model_finish_reason(result),
        "output_truncated": output_truncated,
        "estimated_context_tokens": estimated_context_tokens,
        "response_content_chars": len(content),
    }


def _trim_empty_token_usage(token_usage: dict[str, int]) -> dict[str, int]:
    return {key: value for key, value in token_usage.items() if value > 0}


def _request_text_for_estimate(request: ModelCallRequest) -> str:
    parts: list[str] = []
    for message in request.messages:
        content = message.content
        if isinstance(content, str):
            parts.append(content)
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
            elif item.get("type") == "video" or "video" in item:
                parts.append("[video]")
            elif item.get("type") == "image_url" or "image_url" in item:
                parts.append("[image]")
    return "\n\n".join(parts)
