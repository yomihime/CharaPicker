from __future__ import annotations

import unittest

from scripts.record_release_attestation import (
    ReleaseAttestationError,
    record_release_attestation,
)


def _payload() -> dict:
    return {
        "source": {"repository": "yomihime/CharaPicker"},
        "trust": {
            "signature_policy": "unsigned",
            "signature_inspection_passed": True,
            "signed": False,
            "signature_verified": False,
            "attestation_generated": False,
            "attestation_provider": None,
            "attestation_id": None,
            "attestation_url": None,
        }
    }


class ReleaseAttestationTests(unittest.TestCase):
    def test_records_matching_github_attestation(self) -> None:
        payload = _payload()

        updated = record_release_attestation(
            payload,
            attestation_id="12345",
            attestation_url="https://github.com/yomihime/CharaPicker/attestations/12345",
        )

        self.assertFalse(payload["trust"]["attestation_generated"])
        self.assertTrue(updated["trust"]["attestation_generated"])
        self.assertEqual(updated["trust"]["attestation_provider"], "github")

    def test_rejects_mismatched_attestation_identity(self) -> None:
        with self.assertRaisesRegex(ReleaseAttestationError, "do not match"):
            record_release_attestation(
                _payload(),
                attestation_id="12345",
                attestation_url="https://github.com/yomihime/CharaPicker/attestations/67890",
            )

    def test_rejects_attestation_from_another_repository(self) -> None:
        with self.assertRaisesRegex(ReleaseAttestationError, "repository does not match"):
            record_release_attestation(
                _payload(),
                attestation_id="12345",
                attestation_url="https://github.com/example/other/attestations/12345",
            )

    def test_rejects_attestation_before_signature_inspection(self) -> None:
        payload = _payload()
        payload["trust"]["signature_inspection_passed"] = False

        with self.assertRaisesRegex(ReleaseAttestationError, "unsigned baseline"):
            record_release_attestation(
                payload,
                attestation_id="12345",
                attestation_url="https://github.com/yomihime/CharaPicker/attestations/12345",
            )


if __name__ == "__main__":
    unittest.main()
