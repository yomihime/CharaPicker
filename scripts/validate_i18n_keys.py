from __future__ import annotations

import json
from pathlib import Path


I18N_ROOT = Path(__file__).resolve().parents[1] / "i18n"
REQUIRED_LOCALES = {"zh_CN.json", "zh_TW.json", "en_US.json", "ja_JP.json"}
DEPRECATED_KEYS = {
    "project.processing.placeholder.title",
    "project.processing.placeholder.content",
}
REQUIRED_INSIGHT_META_KEYS = {
    "insight.meta.separator",
    "insight.meta.mediaType",
    "insight.meta.contentForm",
    "insight.meta.unit",
    "insight.meta.material",
    "insight.mediaType.video",
    "insight.mediaType.image",
    "insight.mediaType.audio",
    "insight.mediaType.text",
    "insight.contentForm.unknown",
    "insight.contentForm.anime",
    "insight.contentForm.manga",
    "insight.contentForm.novel",
    "insight.contentForm.script",
    "insight.contentForm.settingBook",
    "insight.contentForm.audioDrama",
    "insight.contentForm.videoProgram",
    "insight.contentForm.imageSet",
    "insight.contentForm.mixed",
}


class DuplicateI18nKeyError(ValueError):
    pass


def load_i18n_messages(path: Path) -> dict[str, str]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise DuplicateI18nKeyError(f"duplicate i18n key in {path.name}: {key}")
            payload[key] = value
        return payload

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(payload, dict):
        raise AssertionError(f"i18n root must be an object: {path.name}")
    return {str(key): str(value) for key, value in payload.items()}


def main() -> None:
    paths = sorted(I18N_ROOT.glob("*.json"))
    actual_locales = {path.name for path in paths}
    if actual_locales != REQUIRED_LOCALES:
        raise AssertionError(
            "i18n locale files mismatch: "
            f"missing={sorted(REQUIRED_LOCALES - actual_locales)} "
            f"extra={sorted(actual_locales - REQUIRED_LOCALES)}"
        )
    key_sets = {path.name: set(load_i18n_messages(path)) for path in paths}
    if not key_sets:
        raise AssertionError("no i18n JSON files found")

    base_name, base_keys = next(iter(key_sets.items()))
    for name, keys in key_sets.items():
        missing = sorted(base_keys - keys)
        extra = sorted(keys - base_keys)
        if missing or extra:
            raise AssertionError(
                f"i18n key mismatch for {name} against {base_name}: "
                f"missing={missing} extra={extra}"
            )
        missing_meta = sorted(REQUIRED_INSIGHT_META_KEYS - keys)
        if missing_meta:
            raise AssertionError(f"insight meta keys missing for {name}: {missing_meta}")
        deprecated = sorted(DEPRECATED_KEYS & keys)
        if deprecated:
            raise AssertionError(f"deprecated i18n keys remain in {name}: {deprecated}")

    print("i18n key validation passed")


if __name__ == "__main__":
    main()
