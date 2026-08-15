from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.atomic_io import DataCorruptionError, backup_path_for
from utils.global_store import YamlFileGlobalStore


class GlobalStoreDurabilityTests(unittest.TestCase):
    def test_nested_values_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = YamlFileGlobalStore(Path(tmp) / "config.yaml")

            store.set("appearance/theme", "dark")

            self.assertEqual(store.get("appearance/theme"), "dark")
            self.assertEqual(store.all()["version"], 1)

    def test_previous_valid_config_becomes_single_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            store = YamlFileGlobalStore(path)
            store.set("appearance/theme", "light")
            store.set("appearance/theme", "dark")

            previous = YamlFileGlobalStore(backup_path_for(path))
            self.assertEqual(previous.get("appearance/theme"), "light")
            self.assertEqual(store.get("appearance/theme"), "dark")

    def test_corrupt_config_is_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            store = YamlFileGlobalStore(path)
            store.set("appearance/theme", "light")
            store.set("appearance/theme", "dark")
            path.write_text("malformed line without a colon\n", encoding="utf-8")

            with self.assertRaises(DataCorruptionError) as raised:
                store.set("appearance/theme", "system")

            self.assertTrue(raised.exception.backup_available)
            self.assertEqual(path.read_text(encoding="utf-8"), "malformed line without a colon\n")

    def test_restore_backup_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            store = YamlFileGlobalStore(path)
            store.set("appearance/theme", "light")
            store.set("appearance/theme", "dark")
            path.write_text("malformed line without a colon\n", encoding="utf-8")

            restored = store.restore_backup()

            self.assertEqual(restored["appearance"]["theme"], "light")
            self.assertEqual(store.get("appearance/theme"), "light")

    def test_empty_existing_config_is_reported_as_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.touch()
            store = YamlFileGlobalStore(path)

            with self.assertRaises(DataCorruptionError) as raised:
                store.all()

            self.assertFalse(raised.exception.backup_available)
            self.assertEqual(path.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
