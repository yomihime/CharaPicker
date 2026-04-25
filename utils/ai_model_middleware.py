from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from string import Formatter
from typing import Any, Literal

from pydantic import BaseModel, Field

from utils.paths import APP_ROOT


LOGGER = logging.getLogger(__name__)
DEFAULT_PROMPTS_PATH = APP_ROOT / "res" / "default_prompts.json"
USER_AGENT = "CharaPicker/0.1"

MessageRole = Literal["system", "user", "assistant"]
ModelBackend = Literal["openai_compatible", "local"]


class ModelMiddlewareError(RuntimeError):
    pass


class PromptNotFoundError(ModelMiddlewareError):
    pass


class ModelCallError(ModelMiddlewareError):
    pass


class ModelMessage(BaseModel):
    role: MessageRole
    content: str


class ModelCallRequest(BaseModel):
    purpose: str
    backend: ModelBackend
    model_name: str
    messages: list[ModelMessage]
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int | None = None
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
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        prompt_file = _PromptFile.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        LOGGER.warning("Default prompts could not be loaded; path=%s", path, exc_info=True)
        raise ModelMiddlewareError(f"Default prompts could not be loaded: {path}") from exc
    return prompt_file.prompts


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
    metadata: dict[str, Any] | None = None,
) -> ModelCallRequest:
    prompts = load_default_prompts()
    template = prompts.get(purpose)
    if template is None:
        raise PromptNotFoundError(f"Prompt purpose is not defined: {purpose}")

    rendered_user = _render_template(template.user_template, variables)
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
        metadata=metadata or {},
        messages=[
            ModelMessage(role="system", content=template.system),
            ModelMessage(role="user", content=rendered_user),
        ],
    )


def call_model(request: ModelCallRequest) -> ModelCallResult:
    if request.backend == "openai_compatible":
        return _call_openai_compatible(request)
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


def _call_openai_compatible(request: ModelCallRequest) -> ModelCallResult:
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

    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    api_key = request.api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    LOGGER.info(
        "Calling model through middleware; "
        "purpose=%s backend=%s endpoint=%s model=%s has_api_key=%s",
        request.purpose,
        request.backend,
        endpoint,
        request.model_name,
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
            raw = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Model call failed; purpose=%s endpoint=%s",
            request.purpose,
            endpoint,
            exc_info=True,
        )
        raise ModelCallError(str(exc)) from exc

    content = _extract_message_content(raw)
    return ModelCallResult(content=content, raw=raw, metadata=request.metadata)


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
    if not isinstance(content, str):
        raise ModelCallError("Model response message content is not text.")
    return content
