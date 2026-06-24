from __future__ import annotations

import unittest
import sys
import types


class _TestQLocale:
    @staticmethod
    def system() -> "_TestQLocale":
        return _TestQLocale()

    def name(self) -> str:
        return "en_US"


qtcore = types.ModuleType("PyQt6.QtCore")
qtcore.QLocale = _TestQLocale
sys.modules.setdefault("PyQt6", types.ModuleType("PyQt6"))
sys.modules.setdefault("PyQt6.QtCore", qtcore)

from core import character_card_compiler as compiler  # noqa: E402
from core import character_card_store as store  # noqa: E402
from core.character_card_constants import STALE_WARNING_COMPILE_INPUTS_CHANGED  # noqa: E402
from core.models import CharacterCard, CharacterCardStatus  # noqa: E402


class CharacterCardQualityTests(unittest.TestCase):
    def test_verified_alias_can_make_direct_evidence(self) -> None:
        payloads = [
            (
                "season_001",
                "episode_001",
                {
                    "targets": ["Lala"],
                    "facts": ["Lala saves Rito during the opening incident."],
                    "evidence_refs": ["season_001/episode_001/chunk_0001"],
                },
            )
        ]

        layers = self._build_layers(["菈菈", "Lala"], payloads)

        direct = layers["direct_evidence_episodes"]
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0]["season_id"], "season_001")
        self.assertIn("facts", direct[0]["source_fields"])
        self.assertIn("Lala", direct[0]["match_terms"])

    def test_targets_alone_are_not_direct_evidence(self) -> None:
        payloads = [
            (
                "season_001",
                "episode_001",
                {
                    "targets": ["Lala"],
                    "facts": ["Rito talks with Haruna after school."],
                    "evidence_refs": ["season_001/episode_001/chunk_0001"],
                },
            )
        ]

        layers = self._build_layers(["Lala"], payloads)

        self.assertEqual(layers["direct_evidence_episodes"], [])
        self.assertEqual(len(layers["mention_evidence_episodes"]), 1)
        self.assertIn("targets", layers["mention_evidence_episodes"][0]["source_fields"])

    def test_mark_card_stale_records_reason(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        card.compile_status = CharacterCardStatus.COMPILED

        stale = store.mark_card_stale(card, STALE_WARNING_COMPILE_INPUTS_CHANGED)

        self.assertEqual(stale.compile_status, CharacterCardStatus.STALE)
        self.assertIn(STALE_WARNING_COMPILE_INPUTS_CHANGED, stale.quality.warnings)

    def test_json_parse_diagnostics_report_repairs(self) -> None:
        result = compiler._parse_json_object_with_diagnostics(
            '```json\n{"warnings": [],}\n```',
            source=compiler.CHARACTER_CARD_COMPILE_PROMPT,
        )

        repairs = {item["repair"] for item in result.diagnostics}
        self.assertEqual(result.payload, {"warnings": []})
        self.assertIn("code_block", repairs)
        self.assertIn("trailing_comma", repairs)

    def test_structured_review_reasons_do_not_enter_plain_warnings(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        card.quality.warnings = ["visible model warning"]
        evidence_layers = {
            "direct_evidence_episodes": [
                {
                    "season_id": "season_001",
                    "episode_id": "episode_001",
                    "warnings": ["chunk_missing_or_failed:chunk_0001"],
                }
            ],
            "mention_evidence_episodes": [],
            "causal_context_episodes": [],
            "season_context": [],
        }
        episode_payloads = [
            (
                "season_001",
                "episode_001",
                {"conflicts": ["Lala has an unresolved cultural conflict"]},
            )
        ]

        compiler._apply_quality_checks(
            card,
            evidence_layers,
            episode_payloads,
            ["Lala"],
            compiler.AliasResolutionResult(source="local"),
            [],
        )

        self.assertTrue(card.quality.needs_review)
        self.assertIn("visible model warning", card.quality.warnings)
        self.assertNotIn(compiler.REVIEW_REASON_KNOWLEDGE_WARNINGS, card.quality.warnings)
        self.assertNotIn(compiler.REVIEW_REASON_CONFLICT_REVIEW, card.quality.warnings)
        reasons = {
            item["reason"]
            for item in card.extensions["charapicker"]["quality_checks"]["needs_review_reasons"]
        }
        self.assertIn(compiler.REVIEW_REASON_KNOWLEDGE_WARNINGS, reasons)
        self.assertIn(compiler.REVIEW_REASON_CONFLICT_REVIEW, reasons)

    def test_evidence_layers_preserve_multi_media_source_metadata(self) -> None:
        payloads = [
            (
                "season_001",
                "episode_001",
                {
                    "extraction_run_id": "run-multi-media",
                    "source_kind": "mixed",
                    "media_types": ["video", "text"],
                    "source_counts": {
                        "full_chunks": 2,
                        "source_trace_units": 2,
                        "source_trace_materials": 2,
                    },
                    "source_trace": {
                        "media_types": ["video", "text"],
                        "material_refs": [
                            {
                                "material_id": "material_video_001",
                                "relative_path": "episode01.mp4",
                                "source_media_type": "video",
                                "content_form": "anime",
                                "origin": "material",
                            },
                            {
                                "material_id": "material_text_001",
                                "relative_path": "episode01.srt",
                                "source_media_type": "text",
                                "content_form": "script",
                                "origin": "material",
                            },
                        ],
                        "unit_refs": ["unit_video_001", "unit_text_001"],
                        "derived_artifact_refs": ["transcript_season_001_episode_001"],
                        "evidence_refs": [
                            {
                                "evidence_id": "evidence_text_001",
                                "unit_ref": "unit_text_001",
                                "locator": {
                                    "relative_path": "episode01.srt",
                                    "time_range": {"start_seconds": 1.0, "end_seconds": 3.0},
                                },
                                "metadata": {"media_type": "text", "unit_kind": "subtitle_text"},
                            }
                        ],
                        "source_breakdown": {
                            "materials": 2,
                            "units": 2,
                            "derived_artifacts": 1,
                            "media_types": {"video": 1, "text": 1},
                        },
                    },
                    "facts": ["Lala protects Rito while the subtitle confirms her line."],
                    "evidence_refs": [
                        "episode01.mp4#native_media",
                        "episode01.srt#time=1.000-3.000",
                    ],
                },
            )
        ]

        layers = self._build_layers(["Lala"], payloads)

        direct = layers["direct_evidence_episodes"]
        self.assertEqual(len(direct), 1)
        source_metadata = direct[0]["source_metadata"]
        self.assertEqual(source_metadata["extraction_run_id"], "run-multi-media")
        self.assertEqual(source_metadata["source_kind"], "mixed")
        self.assertEqual(source_metadata["media_types"], ["video", "text"])
        self.assertEqual(source_metadata["content_forms"], ["anime", "script"])
        self.assertEqual(source_metadata["source_counts"]["full_chunks"], 2)
        self.assertEqual(
            source_metadata["source_trace"]["unit_refs"],
            ["unit_video_001", "unit_text_001"],
        )
        self.assertEqual(
            source_metadata["source_trace"]["derived_artifact_refs"],
            ["transcript_season_001_episode_001"],
        )
        self.assertEqual(
            source_metadata["source_trace"]["evidence_refs"][0]["locator"]["time_range"],
            {"start_seconds": 1.0, "end_seconds": 3.0},
        )

    def test_source_metadata_keeps_legacy_source_kind_out_of_media_types(self) -> None:
        metadata = compiler._payload_source_metadata(
            {
                "source_kind": "audio_transcript",
                "facts": ["Lala speaks in the transcript."],
            }
        )

        self.assertEqual(metadata["source_kind"], "audio_transcript")
        self.assertEqual(metadata["media_types"], [])

    def test_quality_checks_record_evidence_source_profile(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        evidence_layers = {
            "direct_evidence_episodes": [
                {
                    "season_id": "season_001",
                    "episode_id": "episode_001",
                    "warnings": [],
                    "source_metadata": {
                        "source_kind": "mixed",
                        "media_types": ["video", "text"],
                        "content_forms": ["anime", "script"],
                        "evidence_refs": ["episode01.srt#time=1.000-3.000"],
                        "source_trace": {"unit_refs": ["unit_video_001", "unit_text_001"]},
                    },
                }
            ],
            "mention_evidence_episodes": [],
            "causal_context_episodes": [],
            "season_context": [],
        }

        compiler._apply_quality_checks(
            card,
            evidence_layers,
            [],
            ["Lala"],
            compiler.AliasResolutionResult(source="local"),
            [],
        )

        profile = card.extensions["charapicker"]["quality_checks"]["evidence_source_profile"]
        self.assertEqual(profile["media_types"], {"text": 1, "video": 1})
        self.assertEqual(profile["content_forms"], {"anime": 1, "script": 1})
        self.assertEqual(profile["source_kinds"], {"mixed": 1})
        self.assertEqual(profile["entries_with_source_trace"], 1)
        self.assertEqual(profile["entries_with_evidence_refs"], 1)

    def test_compiled_state_records_source_run_ids(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        card.identity.character_name = "Lala"
        payloads = [
            (
                "season_001",
                "episode_001",
                {
                    "extraction_run_id": "run-current",
                    "facts": ["Lala protects Rito."],
                    "chunk_results": [{"chunk_id": "chunk_0001"}],
                },
            ),
            (
                "season_001",
                "episode_002",
                {
                    "extraction_run_id": "run-current",
                    "facts": ["Lala explains her plan."],
                    "chunk_results": [{"chunk_id": "chunk_0002"}],
                },
            ),
        ]

        compiler._apply_compiled_state(
            card,
            {"character": "Lala", "summary": "Princess from Deviluke."},
            [{"season_id": "season_001", "episode_id": "episode_001"}],
            payloads,
        )

        self.assertEqual(card.source_context.source_runs, ["run-current"])

    def _build_layers(
        self,
        match_terms: list[str],
        payloads: list[tuple[str, str, dict]],
    ) -> dict[str, list[dict]]:
        original = compiler._build_season_context
        compiler._build_season_context = lambda *_args, **_kwargs: []
        try:
            return compiler._build_compile_evidence_layers("project-test", match_terms, payloads)
        finally:
            compiler._build_season_context = original


if __name__ == "__main__":
    unittest.main()
