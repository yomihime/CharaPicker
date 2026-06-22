from __future__ import annotations

import json
from pathlib import Path


I18N_ROOT = Path(__file__).resolve().parents[1] / "i18n"
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


def main() -> None:
    key_sets = {
        path.name: set(json.loads(path.read_text(encoding="utf-8")).keys())
        for path in sorted(I18N_ROOT.glob("*.json"))
    }
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

    print("i18n key validation passed")


if __name__ == "__main__":
    main()
