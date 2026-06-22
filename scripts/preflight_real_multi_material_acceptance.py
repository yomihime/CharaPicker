from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import source_scanner  # noqa: E402
from core.extraction_plan import FormalExtractionRunPlan  # noqa: E402
from core.formal_dispatch import build_formal_dispatch_plan  # noqa: E402
from utils.paths import project_paths  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            'Inspect one explicitly selected local project for M18 readiness. '
            'This command does not call a model or write knowledge-base artifacts.'
        )
    )
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--image-input-supported', action='store_true')
    parser.add_argument('--require-media-type', action='append', default=[])
    parser.add_argument('--require-content-form', action='append', default=[])
    parser.add_argument('--require-handler', action='append', default=[])
    return parser


def _counter(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _missing(required: list[str], available: set[str]) -> list[str]:
    return sorted({value.strip() for value in required if value.strip()} - available)


def main() -> None:
    args = _parser().parse_args()
    paths = project_paths(args.project_id)
    if not paths.root.is_dir():
        raise SystemExit(f'project does not exist: {args.project_id}')
    if not paths.materials.is_dir():
        raise SystemExit(f'project materials directory does not exist: {args.project_id}')

    episodes = source_scanner.scan_formal_materials(args.project_id)
    units = [unit for episode in episodes for unit in episode.units]
    if not units:
        raise SystemExit('no extraction units were discovered in materials')

    run_plan = FormalExtractionRunPlan(project_id=args.project_id, episodes=episodes)
    dispatch = build_formal_dispatch_plan(
        run_plan,
        image_input_supported=args.image_input_supported,
    )
    media_types = [unit.media_type.value for unit in units]
    content_forms = [unit.content_form.value for unit in units]
    unit_kinds = [unit.unit_kind or 'unknown' for unit in units]
    handlers = [handler.kind.value for handler in dispatch.handlers]
    unsupported_reasons = [item.reason for item in dispatch.unsupported_units]
    material_ids = {unit.material_ref.material_id for unit in units}

    missing_requirements = {
        'media_types': _missing(args.require_media_type, set(media_types)),
        'content_forms': _missing(args.require_content_form, set(content_forms)),
        'handlers': _missing(args.require_handler, set(handlers)),
    }
    report = {
        'project_id': args.project_id,
        'writes_performed': False,
        'model_calls_performed': False,
        'episode_count': len(episodes),
        'material_count': len(material_ids),
        'unit_count': len(units),
        'media_types': _counter(media_types),
        'content_forms': _counter(content_forms),
        'unit_kinds': _counter(unit_kinds),
        'handler_unit_counts': {
            handler.kind.value: handler.unit_count for handler in dispatch.handlers
        },
        'unsupported_reasons': _counter(unsupported_reasons),
        'image_input_supported_assumption': args.image_input_supported,
        'missing_requirements': missing_requirements,
        'ready': not any(missing_requirements.values()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report['ready']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
