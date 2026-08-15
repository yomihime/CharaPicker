from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.models import ProjectConfig
from utils.atomic_io import DataCorruptionError, backup_path_for
from utils.state_manager import (
    load_project_config,
    restore_project_config_backup,
    save_project_config,
    scan_project_configs,
)


class StateManagerDurabilityTests(unittest.TestCase):
    def _paths(self, root: Path) -> SimpleNamespace:
        knowledge_base = root / "knowledge_base"
        knowledge_base.mkdir(parents=True)
        return SimpleNamespace(
            config=root / "config.json",
            facts=knowledge_base / "facts.json",
            targeted_insights=knowledge_base / "targeted_insights.json",
        )

    def test_save_preserves_one_previous_valid_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project-test"
            paths = self._paths(root)
            config = ProjectConfig(project_id="project-test", name="First")
            with patch("utils.state_manager.ensure_project_tree", return_value=paths):
                save_project_config(config)
                config.name = "Second"
                save_project_config(config)

            self.assertEqual(load_project_config(paths.config).name, "Second")
            self.assertEqual(load_project_config(backup_path_for(paths.config)).name, "First")

    def test_corrupt_project_config_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project-test"
            paths = self._paths(root)
            config = ProjectConfig(project_id="project-test", name="First")
            with patch("utils.state_manager.ensure_project_tree", return_value=paths):
                save_project_config(config)
                config.name = "Second"
                save_project_config(config)
                paths.config.write_text("{broken", encoding="utf-8")
                config.name = "Third"
                with self.assertRaises(DataCorruptionError):
                    save_project_config(config)

            self.assertEqual(paths.config.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(load_project_config(backup_path_for(paths.config)).name, "First")

    def test_scan_reports_recoverable_project_config_and_restore_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects_root = Path(tmp) / "projects"
            paths = self._paths(projects_root / "project-test")
            valid = ProjectConfig(project_id="project-test", name="Recoverable")
            backup_path_for(paths.config).write_text(valid.model_dump_json(), encoding="utf-8")
            paths.config.write_text("{broken", encoding="utf-8")

            result = scan_project_configs(projects_root)

            self.assertEqual(result.configs, [])
            self.assertEqual(len(result.issues), 1)
            self.assertTrue(result.issues[0].backup_available)
            self.assertEqual(paths.config.read_text(encoding="utf-8"), "{broken")

            restored = restore_project_config_backup(paths.config)
            self.assertEqual(restored.name, "Recoverable")

    def test_unknown_project_fields_survive_load_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project-test"
            paths = self._paths(root)
            payload = ProjectConfig(project_id="project-test").model_dump(mode="json")
            payload["future_extension"] = {"enabled": True}
            paths.config.write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_project_config(paths.config)
            with patch("utils.state_manager.ensure_project_tree", return_value=paths):
                save_project_config(loaded)

            saved = json.loads(paths.config.read_text(encoding="utf-8"))
            self.assertEqual(saved["future_extension"], {"enabled": True})


if __name__ == "__main__":
    unittest.main()
