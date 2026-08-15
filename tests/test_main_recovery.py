from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from utils.atomic_io import DataCorruptionError


class MainRecoveryTests(unittest.TestCase):
    def _error(self, root: Path, *, backup_available: bool) -> DataCorruptionError:
        return DataCorruptionError(
            root / "config.yaml",
            root / "config.yaml.bak",
            backup_available=backup_available,
        )

    def test_confirmed_global_recovery_retries_theme_after_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = self._error(Path(tmp), backup_available=True)
            with (
                patch(
                    "utils.theme.apply_theme_preference",
                    side_effect=[error, None],
                ) as apply_theme,
                patch("utils.global_store.restore_global_config_backup") as restore,
                patch("main._prompt_global_config_recovery", return_value=True),
            ):
                recovered = main._apply_theme_with_recovery()

            self.assertTrue(recovered)
            restore.assert_called_once_with()
            self.assertEqual(apply_theme.call_count, 2)

    def test_declined_global_recovery_keeps_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = self._error(Path(tmp), backup_available=True)
            with (
                patch("utils.theme.apply_theme_preference", side_effect=error),
                patch("utils.global_store.restore_global_config_backup") as restore,
                patch("main._prompt_global_config_recovery", return_value=False),
            ):
                recovered = main._apply_theme_with_recovery()

            self.assertFalse(recovered)
            restore.assert_not_called()

    def test_missing_global_backup_stops_without_prompting_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = self._error(Path(tmp), backup_available=False)
            with (
                patch("utils.theme.apply_theme_preference", side_effect=error),
                patch("main._prompt_global_config_recovery") as prompt,
                patch("main._show_global_config_recovery_error") as show_error,
            ):
                recovered = main._apply_theme_with_recovery()

            self.assertFalse(recovered)
            prompt.assert_not_called()
            show_error.assert_called_once_with(error, restore_failed=False)


if __name__ == "__main__":
    unittest.main()
