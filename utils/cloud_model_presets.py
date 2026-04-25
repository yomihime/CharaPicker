from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from PyQt6.QtCore import QSettings

CLOUD_MODEL_PRESETS_KEY = "model/cloudPresets"


@dataclass(slots=True)
class CloudModelPreset:
    name: str
    provider: str
    base_url: str
    api_key: str
    model_name: str


def load_cloud_model_presets() -> list[CloudModelPreset]:
    raw_value = QSettings().value(CLOUD_MODEL_PRESETS_KEY, "[]", str)
    try:
        raw_presets = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_presets, list):
        return []

    presets: list[CloudModelPreset] = []
    for item in raw_presets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        presets.append(
            CloudModelPreset(
                name=name,
                provider=str(item.get("provider", "")),
                base_url=str(item.get("base_url", "")),
                api_key=str(item.get("api_key", "")),
                model_name=str(item.get("model_name", "")),
            )
        )
    return presets


def save_cloud_model_presets(presets: list[CloudModelPreset]) -> None:
    QSettings().setValue(
        CLOUD_MODEL_PRESETS_KEY,
        json.dumps([asdict(preset) for preset in presets], ensure_ascii=False),
    )


def upsert_cloud_model_preset(preset: CloudModelPreset) -> list[CloudModelPreset]:
    presets = [item for item in load_cloud_model_presets() if item.name != preset.name]
    presets.append(preset)
    save_cloud_model_presets(presets)
    return presets


def delete_cloud_model_preset(name: str) -> list[CloudModelPreset]:
    presets = [item for item in load_cloud_model_presets() if item.name != name]
    save_cloud_model_presets(presets)
    return presets
