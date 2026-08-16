from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.inspect_release_signatures import (
    ReleaseSignatureError,
    build_signature_report,
    resolve_powershell_executable,
)


class ReleaseSignatureTests(unittest.TestCase):
    @patch("scripts.inspect_release_signatures.shutil.which")
    def test_signature_inspection_prefers_powershell_7(self, which) -> None:
        which.side_effect = lambda candidate: "C:/Tools/pwsh.exe" if candidate == "pwsh.exe" else None

        self.assertEqual(resolve_powershell_executable(), "C:/Tools/pwsh.exe")

    @patch("scripts.inspect_release_signatures.shutil.which")
    def test_signature_inspection_falls_back_to_windows_powershell(self, which) -> None:
        which.side_effect = lambda candidate: (
            "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            if "WindowsPowerShell" in candidate
            else None
        )

        self.assertTrue(resolve_powershell_executable().endswith("powershell.exe"))

    def test_unsigned_policy_accepts_only_not_signed_executables(self) -> None:
        entries = [
            {
                "name": "CharaPicker.exe",
                "status": "NotSigned",
                "signed": False,
                "signature_verified": False,
            },
            {
                "name": "CharaPickerUpdater.exe",
                "status": "NotSigned",
                "signed": False,
                "signature_verified": False,
            },
        ]

        report = build_signature_report(entries, expected="unsigned")

        self.assertEqual(report["policy"], "unsigned")
        self.assertTrue(report["inspection_passed"])

    def test_unsigned_policy_rejects_signed_or_invalid_executable(self) -> None:
        entries = [
            {
                "name": "CharaPicker.exe",
                "status": "Valid",
                "signed": True,
                "signature_verified": True,
            }
        ]

        with self.assertRaisesRegex(ReleaseSignatureError, "unsigned release policy"):
            build_signature_report(entries, expected="unsigned")


if __name__ == "__main__":
    unittest.main()
