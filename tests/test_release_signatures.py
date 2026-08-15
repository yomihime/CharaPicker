from __future__ import annotations

import unittest

from scripts.inspect_release_signatures import ReleaseSignatureError, build_signature_report


class ReleaseSignatureTests(unittest.TestCase):
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
