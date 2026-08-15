from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.atomic_io import (
    DataCorruptionError,
    backup_path_for,
    restore_backup_atomically,
    write_json_atomically,
    write_text_atomically,
    write_text_atomically_with_backup,
)


class AtomicIoTests(unittest.TestCase):
    def test_text_write_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "data.txt"
            path.parent.mkdir()
            path.write_text("old", encoding="utf-8")

            result = write_text_atomically(path, "new")

            self.assertEqual(result, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_fsync_failure_preserves_old_file_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            path.write_text("old", encoding="utf-8")

            with patch("utils.atomic_io.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    write_text_atomically(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_replace_failure_preserves_old_file_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            path.write_text("old", encoding="utf-8")

            with patch("utils.atomic_io.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    write_text_atomically(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_consecutive_writes_use_distinct_temporary_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            sources: list[Path] = []
            real_replace = os.replace

            def capture_replace(source, destination) -> None:
                sources.append(Path(source))
                real_replace(source, destination)

            with patch("utils.atomic_io.os.replace", side_effect=capture_replace):
                write_text_atomically(path, "first")
                write_text_atomically(path, "second")

            self.assertEqual(len(sources), 2)
            self.assertNotEqual(sources[0].name, sources[1].name)
            self.assertEqual(path.read_text(encoding="utf-8"), "second")

    def test_json_write_uses_utf8_and_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"

            write_json_atomically(path, {"name": "拾卡姬"})

            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(json.loads(text), {"name": "拾卡姬"})

    def test_valid_previous_file_becomes_single_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"revision": 1}', encoding="utf-8")

            write_text_atomically_with_backup(path, '{"revision": 2}', json.loads)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"revision": 2})
            self.assertEqual(
                json.loads(backup_path_for(path).read_text(encoding="utf-8")),
                {"revision": 1},
            )

    def test_corrupt_main_is_not_overwritten_and_valid_backup_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            backup = backup_path_for(path)
            path.write_text("{broken", encoding="utf-8")
            backup.write_text('{"revision": 1}', encoding="utf-8")

            with self.assertRaises(DataCorruptionError) as raised:
                write_text_atomically_with_backup(path, '{"revision": 2}', json.loads)

            self.assertTrue(raised.exception.backup_available)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"revision": 1}')

    def test_valid_backup_is_restored_only_when_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            backup_path_for(path).write_text('{"revision": 1}', encoding="utf-8")

            restore_backup_atomically(path, json.loads)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"revision": 1})


if __name__ == "__main__":
    unittest.main()
