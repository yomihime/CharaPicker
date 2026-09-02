from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_meta import ROOT_DIR


class RuntimeHealthTests(unittest.TestCase):
    def _run_health(self, working_directory: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        return subprocess.run(
            [sys.executable, str(ROOT_DIR / "main.py"), "--health-check"],
            cwd=working_directory,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_source_runtime_health_is_clean(self) -> None:
        completed = self._run_health(ROOT_DIR)
        result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertGreater(result["prompt_count"], 0)
        self.assertEqual(result["model_test_media_count"], 3)
        self.assertTrue(all(count > 0 for count in result["locales"].values()))

    def test_health_entrypoint_does_not_write_to_working_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="CharaPicker 健康检查 ") as tmp:
            working_directory = Path(tmp)
            completed = self._run_health(working_directory)

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(list(working_directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
