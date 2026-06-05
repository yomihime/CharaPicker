from __future__ import annotations

import json
import logging

from utils.app_metadata import HTTP_USER_AGENT
from utils.cloud_model_presets import (
    base_url_has_unresolved_placeholder,
    cloud_model_provider,
)
from utils.network_middleware import NetworkMiddlewareError, read_json, redact_sensitive_text, sanitize_url

LOGGER = logging.getLogger(__name__)


class CloudModelListError(RuntimeError):
    pass


def _models_endpoint(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        raise CloudModelListError("Base URL is required.")
    if base_url.endswith("/models"):
        return base_url
    return f"{base_url}/models"


def fetch_openai_compatible_models(base_url: str, api_key: str) -> list[str]:
    endpoint = _models_endpoint(base_url)
    safe_endpoint = sanitize_url(endpoint)
    LOGGER.info("Fetching cloud model list; endpoint=%s has_api_key=%s", safe_endpoint, bool(api_key.strip()))
    headers = {"User-Agent": HTTP_USER_AGENT}
    api_key = api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        payload = read_json(endpoint, headers=headers, timeout=30)
    except (NetworkMiddlewareError, OSError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Cloud model list fetch failed; endpoint=%s error=%s",
            safe_endpoint,
            redact_sensitive_text(exc),
        )
        LOGGER.debug("Cloud model list fetch traceback; endpoint=%s", safe_endpoint, exc_info=True)
        raise CloudModelListError(redact_sensitive_text(exc)) from exc

    data = payload.get("data")
    if not isinstance(data, list):
        raise CloudModelListError("Response does not include a model list.")

    models = sorted(
        {
            str(item.get("id", "")).strip()
            for item in data
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        }
    )
    if not models:
        LOGGER.warning("Cloud model list response contained no usable models; endpoint=%s", safe_endpoint)
        raise CloudModelListError("No models were returned.")
    LOGGER.info("Cloud model list fetched; endpoint=%s count=%s", safe_endpoint, len(models))
    return models


def fetch_cloud_models(
    provider: str,
    base_url: str,
    api_key: str,
    api_schema: str = "",
) -> list[str]:
    provider_config = cloud_model_provider(provider)
    if base_url_has_unresolved_placeholder(base_url):
        raise CloudModelListError("API address still contains an unresolved placeholder.")
    if provider_config.model_list_kind == "openai_compatible":
        LOGGER.info(
            "Using OpenAI-compatible model-list endpoint; provider=%s api_schema=%s",
            provider_config.provider_id,
            api_schema or "",
        )
        return fetch_openai_compatible_models(base_url, api_key)
    raise CloudModelListError(f"Unsupported cloud model list kind: {provider_config.model_list_kind}")
