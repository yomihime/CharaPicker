from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import paths


class AppRootResolutionTests(unittest.TestCase):
    def test_development_app_root_is_repository_root(self) -> None:
        expected_root = Path(paths.__file__).resolve().parents[1]

        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(paths._resolve_app_root(), expected_root)

    def test_packaged_app_root_uses_executable_directory_not_cwd(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            install_dir = root / "install" / "CharaPicker"
            external_cwd = root / "external-cwd"
            install_dir.mkdir(parents=True)
            external_cwd.mkdir()
            executable = install_dir / "CharaPicker.exe"
            executable.write_bytes(b"")

            try:
                os.chdir(external_cwd)
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(sys, "executable", str(executable)),
                ):
                    self.assertEqual(paths._resolve_app_root(), install_dir.resolve())
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
