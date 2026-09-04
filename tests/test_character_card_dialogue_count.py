from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core.character_card_compiler import (
    CHARACTER_CARD_DIALOGUE_SUPPLEMENT_PROMPT,
    _ensure_extra_dialogue_count,
)
from core.models import (
    CharacterCard,
    CharacterCardCompileVariant,
    CharacterCardDialogueExample,
    CharacterCardDialogueMessage,
    DialogueRole,
)
from utils.ai_model_middleware import ModelCallResult
from utils.cloud_model_presets import CloudModelPreset


def _dialogue(title: str, user: str, assistant: str) -> CharacterCardDialogueExample:
    return CharacterCardDialogueExample(
        title=title,
        messages=[
            CharacterCardDialogueMessage(role=DialogueRole.USER, content=user),
            CharacterCardDialogueMessage(role=DialogueRole.ASSISTANT, content=assistant),
        ],
    )


class CharacterCardDialogueCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.card = CharacterCard(project_id="project-test", card_id="card-test")
        self.card.identity.character_name = "Test Character"
        self.preset = CloudModelPreset(
            name="test",
            provider="openai",
            base_url="https://example.invalid/v1",
            api_key="test-key",
            model_name="test-model",
        )

    def _ensure(
        self,
        variant: CharacterCardCompileVariant = CharacterCardCompileVariant.GENERAL,
        *,
        stages: list[str] | None = None,
    ) -> list[dict]:
        return _ensure_extra_dialogue_count(
            self.card,
            knowledge_summary={"facts": ["evidence"]},
            evidence_layers={"direct_evidence_episodes": [{"facts": ["evidence"]}]},
            cloud_preset=self.preset,
            compile_variant=variant,
            on_stage=stages.append if stages is not None else None,
        )

    def test_blank_count_keeps_model_dialogues_without_supplement(self) -> None:
        self.card.user_metadata.extra_dialogue_count = None
        self.card.dialogue.preset_dialogues = [_dialogue("one", "u1", "a1")]

        with patch(
            "core.character_card_compiler.call_text_model",
            side_effect=AssertionError("supplement request was not expected"),
        ):
            self._ensure()

        self.assertEqual(len(self.card.dialogue.preset_dialogues), 1)
        self.assertEqual(self.card.dialogue.example_dialogues, [])

    def test_zero_count_clears_both_dialogue_surfaces(self) -> None:
        self.card.user_metadata.extra_dialogue_count = 0
        self.card.dialogue.preset_dialogues = [_dialogue("one", "u1", "a1")]
        self.card.dialogue.example_dialogues = [_dialogue("two", "u2", "a2")]

        self._ensure()

        self.assertEqual(self.card.dialogue.preset_dialogues, [])
        self.assertEqual(self.card.dialogue.example_dialogues, [])

    def test_satisfied_count_deduplicates_truncates_and_mirrors_without_request(self) -> None:
        first = _dialogue("first", "u1", "a1")
        second = _dialogue("second", "u2", "a2")
        self.card.user_metadata.extra_dialogue_count = 2
        self.card.dialogue.example_dialogues = [first, first.model_copy(deep=True), second]
        self.card.dialogue.preset_dialogues = [_dialogue("third", "u3", "a3")]

        with patch(
            "core.character_card_compiler.call_text_model",
            side_effect=AssertionError("supplement request was not expected"),
        ):
            self._ensure(CharacterCardCompileVariant.CHARACTER_CARD_V2)

        self.assertEqual([item.title for item in self.card.dialogue.example_dialogues], ["first", "second"])
        self.assertEqual([item.title for item in self.card.dialogue.preset_dialogues], ["first", "second"])

    def test_shortfall_requests_only_missing_groups_and_reaches_exact_count(self) -> None:
        self.card.user_metadata.extra_dialogue_count = 3
        self.card.dialogue.preset_dialogues = [_dialogue("one", "u1", "a1")]
        stages: list[str] = []
        response = {
            "dialogues": [
                _dialogue("two", "u2", "a2").model_dump(mode="json"),
                _dialogue("three", "u3", "a3").model_dump(mode="json"),
            ]
        }

        with patch(
            "core.character_card_compiler.call_text_model",
            return_value=ModelCallResult(content=json.dumps(response)),
        ) as call_model:
            self._ensure(stages=stages)

        request = call_model.call_args.args[0]
        self.assertEqual(request.purpose, CHARACTER_CARD_DIALOGUE_SUPPLEMENT_PROMPT)
        self.assertEqual(request.metadata["missing_count"], 2)
        self.assertEqual(stages, ["supplementing_dialogues"])
        self.assertEqual(len(self.card.dialogue.preset_dialogues), 3)
        self.assertEqual(len(self.card.dialogue.example_dialogues), 3)

    def test_duplicate_or_incomplete_supplements_fail_instead_of_succeeding_short(self) -> None:
        self.card.user_metadata.extra_dialogue_count = 3
        existing = _dialogue("one", "u1", "a1")
        self.card.dialogue.preset_dialogues = [existing]
        response = {
            "dialogues": [
                existing.model_dump(mode="json"),
                {
                    "title": "incomplete",
                    "messages": [{"role": "assistant", "content": "only one side"}],
                },
            ]
        }

        with patch(
            "core.character_card_compiler.call_text_model",
            return_value=ModelCallResult(content=json.dumps(response)),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "target dialogue group count was 3, but only 1 unique complete group",
            ):
                self._ensure()


if __name__ == "__main__":
    unittest.main()
