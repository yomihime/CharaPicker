from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from utils.cloud_model_presets import cloud_model_provider

USER_AGENT = "CharaPicker/0.1"
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
    LOGGER.info("Fetching cloud model list; endpoint=%s has_api_key=%s", endpoint, bool(api_key.strip()))
    headers = {"User-Agent": USER_AGENT}
    api_key = api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(endpoint, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        LOGGER.warning("Cloud model list fetch failed; endpoint=%s", endpoint, exc_info=True)
        raise CloudModelListError(str(exc)) from exc

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
        LOGGER.warning("Cloud model list response contained no usable models; endpoint=%s", endpoint)
        raise CloudModelListError("No models were returned.")
    LOGGER.info("Cloud model list fetched; endpoint=%s count=%s", endpoint, len(models))
    return models


def fetch_cloud_models(provider: str, base_url: str, api_key: str) -> list[str]:
    provider_config = cloud_model_provider(provider)
    if provider_config.model_list_kind == "openai_compatible":
        return fetch_openai_compatible_models(base_url, api_key)
    raise CloudModelListError(f"Unsupported cloud model list kind: {provider_config.model_list_kind}")
