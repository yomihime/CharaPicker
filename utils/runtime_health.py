from __future__ import annotations

import importlib
import json
import os
from typing import Any


REQUIRED_CORE_MODULES = (
    "core.models",
    "core.extractor",
    "core.character_card_compiler",
)


def collect_runtime_health() -> dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from res import APP_ICON_PATH
    from utils.ai_model_middleware import load_default_prompts
    from utils.app_metadata import APP_NAME, APP_VERSION_TAG, format_version_tag
    from utils.i18n import SUPPORTED_LOCALES, load_messages
    from utils.runtime_downloads import load_runtime_download_manifest

    errors: list[str] = []
    created_application = QApplication.instance() is None
    application = QApplication.instance() or QApplication([APP_NAME, "--health-check"])

    for module_name in REQUIRED_CORE_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - exact import failures vary by package
            errors.append(f"core import failed: {module_name}: {type(exc).__name__}")

    locale_counts: dict[str, int] = {}
    for locale in SUPPORTED_LOCALES:
        messages = load_messages(locale)
        locale_counts[locale] = len(messages)
        if not messages:
            errors.append(f"locale resource is empty or unreadable: {locale}")

    try:
        prompt_count = len(load_default_prompts())
        if prompt_count == 0:
            errors.append("default prompt resource contains no prompts")
    except Exception as exc:  # pragma: no cover - reported by packaged negative checks
        prompt_count = 0
        errors.append(f"default prompt resource is unreadable: {type(exc).__name__}")

    try:
        runtime_asset_count = len(load_runtime_download_manifest().assets)
        if runtime_asset_count == 0:
            errors.append("runtime download manifest contains no assets")
    except Exception as exc:  # pragma: no cover - reported by packaged negative checks
        runtime_asset_count = 0
        errors.append(f"runtime download manifest is unreadable: {type(exc).__name__}")

    icon = QIcon(str(APP_ICON_PATH))
    if not APP_ICON_PATH.is_file() or icon.isNull():
        errors.append("application icon resource is missing or unreadable")

    from utils.app_metadata import APP_RELEASE_STAGE, APP_VERSION

    expected_version_tag = format_version_tag(APP_VERSION, APP_RELEASE_STAGE)
    if APP_VERSION_TAG != expected_version_tag:
        errors.append(
            f"application version tag mismatch: actual={APP_VERSION_TAG} expected={expected_version_tag}"
        )

    application.processEvents()
    if created_application:
        application.quit()

    return {
        "status": "ok" if not errors else "error",
        "application": APP_NAME,
        "version": APP_VERSION_TAG,
        "locales": locale_counts,
        "prompt_count": prompt_count,
        "runtime_asset_count": runtime_asset_count,
        "errors": errors,
    }


def run_runtime_health_check() -> int:
    try:
        result = collect_runtime_health()
    except Exception as exc:  # pragma: no cover - last-resort packaged diagnostic
        result = {
            "status": "error",
            "errors": [f"runtime health check crashed: {type(exc).__name__}: {exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result["status"] == "ok" else 1
