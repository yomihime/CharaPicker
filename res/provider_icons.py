from __future__ import annotations

import re
from pathlib import Path


PROVIDER_ICON_ROOT = Path(__file__).resolve().parent / "provider_icons"
FALLBACK_ICON_ID = "cloud"
PROVIDER_ICON_FILES = {
    "aliyun": "aliyun.svg",
    "openai": "openai.svg",
    "deepseek": "deepseek.svg",
    "openrouter": "openrouter.svg",
    FALLBACK_ICON_ID: "cloud.svg",
}


def provider_icon_path(icon_id: str) -> Path | None:
    safe_icon_id = re.sub(r"[^A-Za-z0-9_-]+", "", icon_id.strip()) or FALLBACK_ICON_ID
    file_name = PROVIDER_ICON_FILES.get(safe_icon_id, PROVIDER_ICON_FILES[FALLBACK_ICON_ID])
    path = PROVIDER_ICON_ROOT / file_name
    if path.is_file():
        return path
    fallback_path = PROVIDER_ICON_ROOT / PROVIDER_ICON_FILES[FALLBACK_ICON_ID]
    if fallback_path.is_file():
        return fallback_path
    return None
