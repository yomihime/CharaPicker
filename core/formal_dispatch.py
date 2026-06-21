from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.extraction_plan import ExtractionUnit, FormalExtractionRunPlan, MediaType
from core.image_unit_handler import ImageUnitHandler
from core.text_unit_handler import TextUnitHandler


class FormalDispatchKind(str, Enum):
    VIDEO = "video"
    TEXT = "text"
    IMAGE = "image"
    AUDIO_TRANSCRIPT = "audio_transcript"


@dataclass(frozen=True)
class FormalHandlerDispatch:
    kind: FormalDispatchKind
    unit_refs: tuple[str, ...]

    @property
    def unit_count(self) -> int:
        return len(self.unit_refs)


@dataclass(frozen=True)
class FormalUnsupportedUnit:
    season_id: str
    unit: ExtractionUnit
    reason: str


@dataclass(frozen=True)
class FormalDispatchPlan:
    handlers: tuple[FormalHandlerDispatch, ...]
    unsupported_units: tuple[FormalUnsupportedUnit, ...]

    def has_handler(self, kind: FormalDispatchKind) -> bool:
        return any(handler.kind == kind and handler.unit_refs for handler in self.handlers)

    def handler_unit_count(self, kind: FormalDispatchKind) -> int:
        return sum(handler.unit_count for handler in self.handlers if handler.kind == kind)

    @property
    def supported_unit_count(self) -> int:
        return sum(handler.unit_count for handler in self.handlers)

    @property
    def handler_kinds(self) -> list[str]:
        return [handler.kind.value for handler in self.handlers if handler.unit_refs]


def build_formal_dispatch_plan(
    run_plan: FormalExtractionRunPlan,
    *,
    image_input_supported: bool,
) -> FormalDispatchPlan:
    text_handler = TextUnitHandler()
    image_handler = ImageUnitHandler()
    grouped_units: dict[FormalDispatchKind, list[str]] = {
        FormalDispatchKind.VIDEO: [],
        FormalDispatchKind.TEXT: [],
        FormalDispatchKind.IMAGE: [],
        FormalDispatchKind.AUDIO_TRANSCRIPT: [],
    }
    unsupported_units: list[FormalUnsupportedUnit] = []

    for episode in run_plan.episodes:
        for unit in episode.units:
            if unit.media_type == MediaType.VIDEO:
                grouped_units[FormalDispatchKind.VIDEO].append(unit.unit_id)
                continue

            if unit.media_type == MediaType.TEXT:
                if text_handler.supports(unit):
                    grouped_units[FormalDispatchKind.TEXT].append(unit.unit_id)
                else:
                    unsupported_units.append(_unsupported_unit(episode.season_id, unit))
                continue

            if unit.media_type == MediaType.IMAGE:
                if not image_handler.supports(unit):
                    unsupported_units.append(_unsupported_unit(episode.season_id, unit))
                elif not image_input_supported:
                    unsupported_units.append(
                        FormalUnsupportedUnit(
                            episode.season_id,
                            unit,
                            "model_image_input_not_supported",
                        )
                    )
                else:
                    grouped_units[FormalDispatchKind.IMAGE].append(unit.unit_id)
                continue

            if unit.media_type == MediaType.AUDIO:
                if unit.handler_options.get("transcript_candidate") is True:
                    grouped_units[FormalDispatchKind.AUDIO_TRANSCRIPT].append(unit.unit_id)
                else:
                    unsupported_units.append(_unsupported_unit(episode.season_id, unit))
                continue

            unsupported_units.append(_unsupported_unit(episode.season_id, unit))

    handlers = tuple(
        FormalHandlerDispatch(kind, tuple(unit_refs))
        for kind, unit_refs in grouped_units.items()
        if unit_refs
    )
    return FormalDispatchPlan(
        handlers=handlers,
        unsupported_units=tuple(sorted(unsupported_units, key=_unsupported_sort_key)),
    )


def _unsupported_unit(season_id: str, unit: ExtractionUnit) -> FormalUnsupportedUnit:
    reason = str(unit.material_ref.metadata.get("support_reason", "")).strip()
    return FormalUnsupportedUnit(
        season_id,
        unit,
        reason or "formal_handler_not_available",
    )


def _unsupported_sort_key(item: FormalUnsupportedUnit) -> tuple[str, str, str, str]:
    unit = item.unit
    return (
        item.season_id,
        unit.episode_id,
        unit.material_ref.relative_path.lower(),
        unit.unit_id,
    )
