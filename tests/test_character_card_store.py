from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import character_card_store as store
from core.models import CharacterCard
from utils.atomic_io import DataCorruptionError, backup_path_for


class CharacterCardStoreDurabilityTests(unittest.TestCase):
    def _card_path(self, root: Path, card_id: str = "card-test") -> Path:
        path = root / card_id / "card.json"
        path.parent.mkdir(parents=True)
        return path

    def _path_patch(self, root: Path):
        return patch(
            "core.character_card_store.kb.character_card_json_path",
            side_effect=lambda _project_id, card_id: root / card_id / "card.json",
        )

    def test_save_preserves_one_previous_valid_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._card_path(root)
            card = CharacterCard(project_id="project-test", card_id="card-test")
            card.user_metadata.notes = "First"
            with self._path_patch(root):
                store.save_card(card)
                card.user_metadata.notes = "Second"
                store.save_card(card)

            current = json.loads(path.read_text(encoding="utf-8"))
            previous = json.loads(backup_path_for(path).read_text(encoding="utf-8"))
            self.assertEqual(current["user_metadata"]["notes"], "Second")
            self.assertEqual(previous["user_metadata"]["notes"], "First")

    def test_corrupt_card_is_not_overwritten_and_can_be_explicitly_restored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._card_path(root)
            card = CharacterCard(project_id="project-test", card_id="card-test")
            card.user_metadata.notes = "Recoverable"
            with self._path_patch(root):
                store.save_card(card)
                card.user_metadata.notes = "Current"
                store.save_card(card)
                path.write_text("{broken", encoding="utf-8")
                card.user_metadata.notes = "Refused"
                with self.assertRaises(DataCorruptionError):
                    store.save_card(card)
                restored = store.restore_card_backup("project-test", "card-test")

            self.assertEqual(restored.user_metadata.notes, "Recoverable")

    def test_unknown_card_extension_survives_load_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._card_path(root)
            payload = CharacterCard(project_id="project-test", card_id="card-test").model_dump(
                mode="json"
            )
            payload["future_extension"] = {"preserve": True}
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self._path_patch(root):
                card = store.load_card("project-test", "card-test")
                store.save_card(card)
                reloaded = store.load_card("project-test", "card-test")

            self.assertEqual(reloaded.model_extra["future_extension"], {"preserve": True})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["future_extension"],
                {"preserve": True},
            )

    def test_scan_reports_corrupt_card_without_restoring_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._card_path(root)
            valid = CharacterCard(project_id="project-test", card_id="card-test")
            backup_path_for(path).write_text(valid.model_dump_json(), encoding="utf-8")
            path.write_text("{broken", encoding="utf-8")

            with (
                patch("core.character_card_store.kb.character_cards_root_path", return_value=root),
                self._path_patch(root),
            ):
                result = store.scan_card_summaries("project-test")

            self.assertEqual(result.summaries, [])
            self.assertEqual(len(result.issues), 1)
            self.assertTrue(result.issues[0].backup_available)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
