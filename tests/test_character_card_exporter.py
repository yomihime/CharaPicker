from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.character_card_exporter import (
    export_astrbot_persona_json,
    export_markdown,
    export_selected_targets,
)
from core.character_card_formats import to_astrbot_persona_json
from core.models import (
    CharacterCard,
    CharacterCardDialogueExample,
    CharacterCardDialogueMessage,
    CharacterCardExportStatus,
    CharacterCardExportTarget,
    DialogueRole,
)


class CharacterCardExporterTests(unittest.TestCase):
    def test_astrbot_persona_payload_matches_official_import_shape(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        card.identity.display_name = "春奈"
        card.prompt_surfaces.system_prompt = "你是春奈，请始终使用自然、克制的语气回复。"
        card.dialogue.preset_dialogues = [
            CharacterCardDialogueExample(
                title="Greeting",
                messages=[
                    CharacterCardDialogueMessage(role=DialogueRole.USER, content="早上好。"),
                    CharacterCardDialogueMessage(role=DialogueRole.ASSISTANT, content="早上好，今天也请多关照。"),
                ],
            )
        ]

        formatted = to_astrbot_persona_json(card)

        self.assertEqual(
            formatted.payload,
            {
                "persona_id": "春奈",
                "system_prompt": "你是春奈，请始终使用自然、克制的语气回复。",
                "begin_dialogs": ["早上好。", "早上好，今天也请多关照。"],
            },
        )
        self.assertEqual(formatted.warnings, [])

    def test_astrbot_persona_skips_incomplete_dialogue_and_keeps_pairs_even(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        card.prompt_surfaces.system_prompt = "A complete AstrBot system prompt."
        card.dialogue.preset_dialogues = [
            CharacterCardDialogueExample(
                messages=[CharacterCardDialogueMessage(role=DialogueRole.USER, content="Missing reply")]
            ),
            CharacterCardDialogueExample(
                messages=[
                    CharacterCardDialogueMessage(role=DialogueRole.USER, content="Complete user"),
                    CharacterCardDialogueMessage(role=DialogueRole.ASSISTANT, content="Complete assistant"),
                ]
            ),
        ]

        formatted = to_astrbot_persona_json(card)

        self.assertEqual(formatted.payload["begin_dialogs"], ["Complete user", "Complete assistant"])
        self.assertEqual(len(formatted.payload["begin_dialogs"]) % 2, 0)
        self.assertIn("preset dialogue 1 skipped because one side is empty", formatted.warnings)

    def test_astrbot_persona_id_ignores_blank_display_name_and_limits_length(self) -> None:
        card = CharacterCard(project_id="project-test", card_id="card-test")
        card.identity.display_name = "   "
        card.identity.character_name = "角" * 300
        card.prompt_surfaces.system_prompt = "A complete AstrBot system prompt."

        formatted = to_astrbot_persona_json(card)

        self.assertEqual(formatted.payload["persona_id"], "角" * 255)

    def test_astrbot_persona_export_writes_importable_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            card = CharacterCard(project_id="project-test", card_id="card-test")
            card.identity.character_name = "拉拉"
            card.prompt_surfaces.persona_prompt = "你是拉拉，并会保持角色设定。"
            card.prompt_surfaces.first_message = "很高兴见到你。"

            result = export_astrbot_persona_json(card, output_dir=output_dir)

            self.assertEqual(result.target, CharacterCardExportTarget.ASTRBOT_PERSONA_JSON)
            self.assertEqual(result.status, CharacterCardExportStatus.SUCCESS)
            self.assertEqual(Path(result.output_path).name, "card-test.astrbot-persona.json")
            self.assertEqual(
                Path(result.output_path).read_text(encoding="utf-8"),
                '{\n  "persona_id": "拉拉",\n  "system_prompt": "你是拉拉，并会保持角色设定。",\n'
                '  "begin_dialogs": [\n    "Please introduce yourself first.",\n    "很高兴见到你。"\n  ]\n}',
            )
            self.assertEqual(list(output_dir.glob(".tmp-*.tmp")), [])

    def test_astrbot_persona_and_copy_targets_can_be_exported_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            card = CharacterCard(project_id="project-test", card_id="card-test")
            card.prompt_surfaces.system_prompt = "A complete AstrBot system prompt."
            card.prompt_surfaces.first_message = "Hello from the character."

            results = export_selected_targets(
                card,
                [
                    CharacterCardExportTarget.ASTRBOT_PERSONA_JSON,
                    CharacterCardExportTarget.ASTRBOT_COPY,
                ],
                output_dir=output_dir,
            )

            self.assertEqual([result.status for result in results], [CharacterCardExportStatus.SUCCESS] * 2)
            self.assertEqual(
                {Path(result.output_path).name for result in results},
                {"card-test.astrbot-persona.json", "card-test.astrbot-copy.md"},
            )

    def test_export_publishes_complete_file_without_temporary_leftovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            card = CharacterCard(project_id="project-test", card_id="card-test")

            result = export_markdown(card, output_dir=output_dir)

            self.assertEqual(result.status, CharacterCardExportStatus.SUCCESS)
            self.assertTrue(Path(result.output_path).is_file())
            self.assertEqual(list(output_dir.glob(".tmp-*.tmp")), [])

    def test_failed_export_replace_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            output_path = output_dir / "card-test.md"
            output_path.write_text("previous export", encoding="utf-8")
            card = CharacterCard(project_id="project-test", card_id="card-test")

            with patch("utils.atomic_io.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    export_markdown(card, output_dir=output_dir)

            self.assertEqual(output_path.read_text(encoding="utf-8"), "previous export")
            self.assertEqual(list(output_dir.glob(".tmp-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
