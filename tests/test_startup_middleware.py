from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.models import ProjectConfig
from utils.atomic_io import DataCorruptionError
from utils.startup_middleware import warmup_startup_context
from utils.state_manager import ProjectConfigScanResult


class StartupMiddlewareTests(unittest.TestCase):
    def test_warmup_preserves_project_configuration_issues_for_ui_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            issue = DataCorruptionError(
                root / "project" / "config.json",
                root / "project" / "config.json.bak",
                backup_available=True,
            )
            config = ProjectConfig(project_id="project-test", name="Healthy")
            scan = ProjectConfigScanResult(configs=[config], issues=[issue])
            with (
                patch("utils.startup_middleware.scan_project_configs", return_value=scan),
                patch("utils.startup_middleware.list_available_device_options", return_value=[]),
                patch("utils.startup_middleware.has_ffmpeg_binary", return_value=False),
                patch("utils.startup_middleware.has_llamacpp_binary", return_value=False),
                patch(
                    "utils.startup_middleware.whisper_status",
                    return_value=SimpleNamespace(ready=False),
                ),
                patch("utils.startup_middleware.list_local_model_candidates", return_value=[]),
                patch("utils.startup_middleware.load_cloud_model_presets", return_value=[]),
            ):
                snapshot = warmup_startup_context()

            self.assertEqual(snapshot.project_configs, [config])
            self.assertEqual(snapshot.project_config_issues, [issue])
            self.assertFalse(snapshot.ffmpeg_ready)
            self.assertEqual(snapshot.encoder_options, [])
            self.assertFalse(snapshot.llamacpp_ready)
            self.assertFalse(snapshot.whisper_status.ready)
            self.assertEqual(snapshot.local_models, [])
            self.assertEqual(snapshot.cloud_presets, [])


if __name__ == "__main__":
    unittest.main()
