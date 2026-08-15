from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_i18n_keys import DuplicateI18nKeyError, load_i18n_messages


class I18nValidationTests(unittest.TestCase):
    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "messages.json"
            path.write_text('{"duplicate": "first", "duplicate": "second"}\n', encoding="utf-8")

            with self.assertRaisesRegex(DuplicateI18nKeyError, "duplicate"):
                load_i18n_messages(path)

    def test_unique_json_keys_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "messages.json"
            path.write_text('{"first": "one", "second": "two"}\n', encoding="utf-8")

            self.assertEqual(
                load_i18n_messages(path),
                {"first": "one", "second": "two"},
            )


if __name__ == "__main__":
    unittest.main()
