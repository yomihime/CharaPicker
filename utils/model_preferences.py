from __future__ import annotations

from typing import Literal

from utils.global_store import get_global_value, set_global_value


ModelPageMode = Literal["local", "cloud"]

MODEL_PAGE_MODE_KEY = "model/lastMode"
MODEL_PAGE_CLOUD_PRESET_KEY = "model/lastCloudPreset"
MODEL_PAGE_LOCAL_MODEL_KEY = "model/lastLocalModel"


def last_model_page_mode() -> ModelPageMode:
    value = str(get_global_value(MODEL_PAGE_MODE_KEY, "local")).strip()
    return "cloud" if value == "cloud" else "local"


def set_last_model_page_mode(mode: ModelPageMode) -> None:
    set_global_value(MODEL_PAGE_MODE_KEY, mode)


def last_cloud_preset_name() -> str:
    return str(get_global_value(MODEL_PAGE_CLOUD_PRESET_KEY, "")).strip()


def set_last_cloud_preset_name(name: str) -> None:
    set_global_value(MODEL_PAGE_CLOUD_PRESET_KEY, name.strip())


def last_local_model_path() -> str:
    return str(get_global_value(MODEL_PAGE_LOCAL_MODEL_KEY, "")).strip()


def set_last_local_model_path(path: str) -> None:
    set_global_value(MODEL_PAGE_LOCAL_MODEL_KEY, path.strip())
