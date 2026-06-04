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
