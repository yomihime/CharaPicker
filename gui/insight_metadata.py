from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


Translate = Callable[..., str]

MEDIA_TYPE_LABEL_KEYS = {
    'video': 'insight.mediaType.video',
    'image': 'insight.mediaType.image',
    'audio': 'insight.mediaType.audio',
    'text': 'insight.mediaType.text',
}
CONTENT_FORM_LABEL_KEYS = {
    'unknown': 'insight.contentForm.unknown',
    'anime': 'insight.contentForm.anime',
    'manga': 'insight.contentForm.manga',
    'novel': 'insight.contentForm.novel',
    'script': 'insight.contentForm.script',
    'setting_book': 'insight.contentForm.settingBook',
    'audio_drama': 'insight.contentForm.audioDrama',
    'video_program': 'insight.contentForm.videoProgram',
    'image_set': 'insight.contentForm.imageSet',
    'mixed': 'insight.contentForm.mixed',
}


def insight_meta_text(event: dict, translate: Translate) -> str:
    meta = event.get('meta')
    if not isinstance(meta, dict):
        return ''
    parts: list[str] = []
    media_type = _localized_value(meta.get('media_type'), MEDIA_TYPE_LABEL_KEYS, translate)
    if media_type:
        parts.append(translate('insight.meta.mediaType', value=media_type))
    content_form_value = str(meta.get('content_form') or '').strip()
    if content_form_value and content_form_value != 'unknown':
        content_form = _localized_value(
            content_form_value,
            CONTENT_FORM_LABEL_KEYS,
            translate,
        )
        parts.append(translate('insight.meta.contentForm', value=content_form))
    unit_id = str(meta.get('unit_id') or '').strip()
    if unit_id:
        parts.append(translate('insight.meta.unit', value=unit_id))
    material_name = _material_display_name(meta)
    if material_name:
        parts.append(translate('insight.meta.material', value=material_name))
    return translate('insight.meta.separator').join(parts)


def _localized_value(value: object, mapping: dict[str, str], translate: Translate) -> str:
    normalized = str(value or '').strip()
    if not normalized:
        return ''
    label_key = mapping.get(normalized)
    return translate(label_key) if label_key else normalized


def _material_display_name(meta: dict) -> str:
    value = str(meta.get('relative_path') or meta.get('source_path') or '').strip()
    if not value:
        return ''
    return Path(value).name or value
