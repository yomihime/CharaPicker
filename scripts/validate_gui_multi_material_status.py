from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.insight_metadata import (  # noqa: E402
    CONTENT_FORM_LABEL_KEYS,
    MEDIA_TYPE_LABEL_KEYS,
    insight_meta_text,
)


PROJECT_PAGE = ROOT / 'gui' / 'pages' / 'project_page.py'
FORBIDDEN_PROJECT_PAGE_IMPORTS = {
    'core.extractor',
    'core.knowledge_base',
    'core.text_unit_handler',
    'core.image_unit_handler',
    'core.native_media_insight_handler',
    'utils.ai_model_middleware',
}
TRANSLATIONS = {
    'insight.meta.separator': ' | ',
    'insight.meta.mediaType': 'Media: {value}',
    'insight.meta.contentForm': 'Form: {value}',
    'insight.meta.unit': 'Unit: {value}',
    'insight.meta.material': 'Material: {value}',
    'insight.mediaType.video': 'Video',
    'insight.contentForm.manga': 'Manga',
}


def _translate(key: str, **kwargs: object) -> str:
    return TRANSLATIONS.get(key, key).format(**kwargs)


def _validate_metadata_mapping() -> None:
    assert set(MEDIA_TYPE_LABEL_KEYS) == {'video', 'image', 'audio', 'text'}
    assert set(CONTENT_FORM_LABEL_KEYS) == {
        'unknown',
        'anime',
        'manga',
        'novel',
        'script',
        'setting_book',
        'audio_drama',
        'video_program',
        'image_set',
        'mixed',
    }
    text = insight_meta_text(
        {
            'meta': {
                'media_type': 'video',
                'content_form': 'manga',
                'unit_id': 'unit_video_001',
                'relative_path': 'season_01/chapter_02/page_003.png',
            }
        },
        _translate,
    )
    assert text == (
        'Media: Video | Form: Manga | Unit: unit_video_001 | Material: page_003.png'
    )

    unknown = insight_meta_text(
        {'meta': {'media_type': 'custom_media', 'content_form': 'unknown'}},
        _translate,
    )
    assert unknown == 'Media: custom_media'
    assert insight_meta_text({'meta': None}, _translate) == ''


def _validate_project_page_boundary() -> None:
    source = PROJECT_PAGE.read_text(encoding='utf-8')
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
    forbidden = sorted(FORBIDDEN_PROJECT_PAGE_IMPORTS & imported_modules)
    assert not forbidden, f'project page imports extraction implementation: {forbidden}'
    assert 'self.extractionRequested.emit(' in source


def main() -> None:
    _validate_metadata_mapping()
    _validate_project_page_boundary()
    print('GUI multi-material status validation passed')


if __name__ == '__main__':
    main()
