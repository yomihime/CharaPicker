from __future__ import annotations

import json
import urllib.error
import urllib.request

USER_AGENT = "CharaPicker/0.1"


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
    headers = {"User-Agent": USER_AGENT}
    api_key = api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(_models_endpoint(base_url), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
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
        raise CloudModelListError("No models were returned.")
    return models
