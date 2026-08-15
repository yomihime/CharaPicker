from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.character_card_exporter import export_markdown
from core.models import CharacterCard, CharacterCardExportStatus


class CharacterCardExporterTests(unittest.TestCase):
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
