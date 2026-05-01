from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path
from string import Formatter
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from utils.paths import APP_ROOT
from utils.prompt_preferences import prompt_override


LOGGER = logging.getLogger(__name__)
DEFAULT_PROMPTS_PATH = APP_ROOT / "res" / "default_prompts.json"
USER_AGENT = "CharaPicker/0.1"

MessageRole = Literal["system", "user", "assistant"]
ModelBackend = Literal["openai_compatible", "dashscope", "local"]
ModelMessageContent = str | list[dict[str, Any]]


class ModelMiddlewareError(RuntimeError):
    pass


class PromptNotFoundError(ModelMiddlewareError):
    pass


class ModelCallError(ModelMiddlewareError):
    pass


class ModelMessage(BaseModel):
    role: MessageRole
    content: ModelMessageContent


class ModelCallRequest(BaseModel):
    purpose: str
    backend: ModelBackend
    model_name: str
    messages: list[ModelMessage]
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int | None = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCallResult(BaseModel):
    content: str
    raw: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class _PromptTemplate(BaseModel):
    system: str
    user_template: str


class _PromptFile(BaseModel):
    version: int = 1
    prompts: dict[str, _PromptTemplate]


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def load_default_prompts(path: Path = DEFAULT_PROMPTS_PATH) -> dict[str, _PromptTemplate]:
    candidate_paths = _resolve_default_prompt_candidates(path)
    resolved_path = next((candidate for candidate in candidate_paths if candidate.is_file()), path)
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        prompt_file = _PromptFile.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        LOGGER.warning(
            "Default prompts could not be loaded; path=%s candidates=%s",
            resolved_path,
            [str(item) for item in candidate_paths],
            exc_info=True,
        )
        raise ModelMiddlewareError(
            f"Default prompts could not be loaded: {resolved_path}"
        ) from exc
    return prompt_file.prompts


def _resolve_default_prompt_candidates(primary_path: Path) -> list[Path]:
    candidates: list[Path] = [primary_path]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "res" / "default_prompts.json")
        candidates.append(exe_dir / "_internal" / "res" / "default_prompts.json")
    return candidates


def build_model_call_request(
    *,
    purpose: str,
    backend: ModelBackend,
    model_name: str,
    variables: dict[str, Any],
    base_url: str = "",
    api_key: str = "",
    temperature: float = 0.2,
    max_tokens: int | None = None,
    stream: bool = False,
    metadata: dict[str, Any] | None = None,
) -> ModelCallRequest:
    prompts = load_default_prompts()
    template = prompts.get(purpose)
    if template is None:
        raise PromptNotFoundError(f"Prompt purpose is not defined: {purpose}")

    override = prompt_override(purpose)
    system_prompt = override.system.strip() or template.system
    user_template = override.user_template.strip() or template.user_template
    rendered_user = _render_template(user_template, variables)
    LOGGER.debug(
        "Model call request built; purpose=%s backend=%s model=%s has_api_key=%s",
        purpose,
        backend,
        model_name,
        bool(api_key),
    )
    return ModelCallRequest(
        purpose=purpose,
        backend=backend,
        model_name=model_name.strip(),
        base_url=base_url.strip(),
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
        metadata=metadata or {},
        messages=[
            ModelMessage(role="system", content=system_prompt),
            ModelMessage(role="user", content=rendered_user),
        ],
    )


def call_model(
    request: ModelCallRequest,
    *,
    on_stream_delta: Callable[[str], None] | None = None,
) -> ModelCallResult:
    if request.backend == "openai_compatible":
        return _call_openai_compatible(request, on_stream_delta=on_stream_delta)
    if request.backend == "dashscope":
        return _call_dashscope(request)
    if request.backend == "local":
        raise ModelCallError(
            "Local model execution is not wired yet; "
            "use this middleware entrypoint when it is added."
        )
    raise ModelCallError(f"Unsupported model backend: {request.backend}")


def _render_template(template: str, variables: dict[str, Any]) -> str:
    normalized = {key: _stringify_value(value) for key, value in variables.items()}
    field_names = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name}
    missing = sorted(field_names - normalized.keys())
    if missing:
        LOGGER.warning("Prompt variables missing; keys=%s", missing)
    return template.format_map(_SafeFormatDict(normalized))


def _stringify_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json(indent=2)
    return json.dumps(value, ensure_ascii=False, indent=2)


def _chat_completions_endpoint(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        raise ModelCallError("Base URL is required for OpenAI-compatible calls.")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _dashscope_api_url(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        return "https://dashscope.aliyuncs.com/api/v1"
    if base_url.endswith("/compatible-mode/v1"):
        return base_url[: -len("/compatible-mode/v1")] + "/api/v1"
    if base_url.endswith("/chat/completions"):
        return _dashscope_api_url(base_url[: -len("/chat/completions")])
    if base_url.endswith("/api/v1"):
        return base_url
    return base_url


def _call_dashscope(request: ModelCallRequest) -> ModelCallResult:
    if not request.model_name:
        raise ModelCallError("Model name is required.")
    try:
        import dashscope
        from dashscope import MultiModalConversation
    except ImportError as exc:
        raise ModelCallError(
            "DashScope Python SDK is required for local file path video input. "
            "Install dependencies from requirements.txt first."
        ) from exc

    api_key = request.api_key.strip()
    dashscope.base_http_api_url = _dashscope_api_url(request.base_url)
    messages = [_to_dashscope_message(message) for message in request.messages]
    LOGGER.info(
        "Calling model through DashScope SDK; purpose=%s endpoint=%s model=%s has_api_key=%s",
        request.purpose,
        dashscope.base_http_api_url,
        request.model_name,
        bool(api_key),
    )
    try:
        response = MultiModalConversation.call(
            api_key=api_key or None,
            model=request.model_name,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "DashScope model call failed; purpose=%s endpoint=%s",
            request.purpose,
            dashscope.base_http_api_url,
            exc_info=True,
        )
        raise ModelCallError(str(exc)) from exc

    raw = _dashscope_response_to_dict(response)
    status_code = raw.get("status_code")
    if isinstance(status_code, int) and status_code >= 400:
        message = raw.get("message") or raw.get("code") or "DashScope call failed"
        raise ModelCallError(str(message))

    content = _extract_dashscope_content(raw)
    usage = _extract_token_usage(raw)
    if not usage:
        output = raw.get("output")
        if isinstance(output, dict):
            usage = _extract_token_usage(output)
    metadata = dict(request.metadata)
    if usage:
        metadata["token_usage"] = usage
    return ModelCallResult(content=content, raw=raw, metadata=metadata)


def _to_dashscope_message(message: ModelMessage) -> dict[str, Any]:
    if isinstance(message.content, str):
        return {"role": message.role, "content": [{"text": message.content}]}

    content: list[dict[str, Any]] = []
    for item in message.content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text" or "text" in item:
            text = item.get("text")
            if isinstance(text, str):
                content.append({"text": text})
            continue
        if "video" in item:
            video = item.get("video")
            if isinstance(video, str):
                video_part: dict[str, Any] = {"video": video}
                fps = item.get("fps")
                if isinstance(fps, (int, float)):
                    video_part["fps"] = fps
                content.append(video_part)
            continue
        if item_type == "video_url":
            video_url = item.get("video_url")
            if isinstance(video_url, dict) and isinstance(video_url.get("url"), str):
                video_part = {"video": video_url["url"]}
                fps = item.get("fps")
                if isinstance(fps, (int, float)):
                    video_part["fps"] = fps
                content.append(video_part)
    return {"role": message.role, "content": content}


def _dashscope_response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, dict):
            return value
    try:
        return json.loads(json.dumps(response, default=lambda item: getattr(item, "__dict__", str(item))))
    except (TypeError, ValueError):
        return {"response": str(response)}


def _extract_dashscope_content(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, dict):
        return _extract_message_content(payload)
    choices = output.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelCallError("DashScope response does not include choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ModelCallError("DashScope response choice is not an object.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ModelCallError("DashScope response choice does not include a message.")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)
    raise ModelCallError("DashScope response message content is not text.")


def _call_openai_compatible(
    request: ModelCallRequest,
    *,
    on_stream_delta: Callable[[str], None] | None = None,
) -> ModelCallResult:
    endpoint = _chat_completions_endpoint(request.base_url)
    if not request.model_name:
        raise ModelCallError("Model name is required.")

    payload: dict[str, Any] = {
        "model": request.model_name,
        "messages": [message.model_dump() for message in request.messages],
        "temperature": request.temperature,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    api_key = request.api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    LOGGER.info(
        "Calling model through middleware; "
        "purpose=%s backend=%s endpoint=%s model=%s stream=%s has_api_key=%s",
        request.purpose,
        request.backend,
        endpoint,
        request.model_name,
        request.stream,
        bool(api_key),
    )
    http_request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=120) as response:
            if request.stream:
                return _read_streamed_response(response, request, on_stream_delta=on_stream_delta)
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            payload = exc.read()
            if payload:
                error_body = payload.decode("utf-8", errors="replace").strip()
        except OSError:
            error_body = ""
        LOGGER.warning(
            "Model call failed; purpose=%s endpoint=%s status=%s body=%s",
            request.purpose,
            endpoint,
            exc.code,
            error_body,
            exc_info=True,
        )
        detail = f"HTTP {exc.code} {exc.reason}"
        if error_body:
            detail = f"{detail}: {error_body}"
        raise ModelCallError(detail) from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Model call failed; purpose=%s endpoint=%s",
            request.purpose,
            endpoint,
            exc_info=True,
        )
        raise ModelCallError(str(exc)) from exc

    content = _extract_message_content(raw)
    usage = _extract_token_usage(raw)
    if usage:
        LOGGER.info(
            "Model token usage; purpose=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            request.purpose,
            request.model_name,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
    metadata = dict(request.metadata)
    if usage:
        metadata["token_usage"] = usage
    return ModelCallResult(content=content, raw=raw, metadata=metadata)


def _read_streamed_response(
    response: Any,
    request: ModelCallRequest,
    *,
    on_stream_delta: Callable[[str], None] | None = None,
) -> ModelCallResult:
    chunks: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        payload_text = line[5:].strip()
        if payload_text == "[DONE]":
            break
        try:
            chunk = json.loads(payload_text)
        except json.JSONDecodeError:
            continue
        chunks.append(chunk)
        delta_text = _extract_stream_delta_text(chunk)
        if delta_text:
            text_parts.append(delta_text)
            if on_stream_delta is not None:
                for char in delta_text:
                    on_stream_delta(char)

    content = "".join(text_parts).strip()
    if not content and chunks:
        try:
            content = _extract_message_content(chunks[-1]).strip()
        except ModelCallError:
            content = ""
    if not content:
        raise ModelCallError("Streamed model response does not include text content.")
    usage = _extract_token_usage_from_chunks(chunks)
    if usage:
        LOGGER.info(
            "Model token usage (stream); purpose=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            request.purpose,
            request.model_name,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
    metadata = dict(request.metadata)
    if usage:
        metadata["token_usage"] = usage
    return ModelCallResult(
        content=content,
        raw={"stream": True, "chunks": chunks},
        metadata=metadata,
    )


def _extract_token_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    prompt_tokens = usage.get("prompt_tokens")
    if not isinstance(prompt_tokens, int):
        prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("completion_tokens")
    if not isinstance(completion_tokens, int):
        completion_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    if not isinstance(total_tokens, int) and isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        total_tokens = prompt_tokens + completion_tokens

    normalized: dict[str, int] = {}
    if isinstance(prompt_tokens, int):
        normalized["prompt_tokens"] = prompt_tokens
    if isinstance(completion_tokens, int):
        normalized["completion_tokens"] = completion_tokens
    if isinstance(total_tokens, int):
        normalized["total_tokens"] = total_tokens
    return normalized


def _extract_token_usage_from_chunks(chunks: list[dict[str, Any]]) -> dict[str, int]:
    for chunk in reversed(chunks):
        usage = _extract_token_usage(chunk)
        if usage:
            return usage
    return {}


def _extract_stream_delta_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    delta = first_choice.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts)
    return ""


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelCallError("Model response does not include choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ModelCallError("Model response choice is not an object.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ModelCallError("Model response choice does not include a message.")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)
    raise ModelCallError("Model response message content is not text.")
