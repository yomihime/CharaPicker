from __future__ import annotations

import hashlib
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from utils.download_integrity import DownloadIntegrityError, download_staged_file


class _Response:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_length: str | None = None,
        status_code: int = 200,
    ) -> None:
        self.status_code = status_code
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length
        self._chunks = chunks

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        _ = chunk_size
        return self._chunks


class DownloadIntegrityTests(unittest.TestCase):
    def test_missing_content_length_is_allowed_under_stream_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            destination = Path(temp_name) / "asset.bin"
            with patch(
                "utils.download_integrity.open_response",
                return_value=nullcontext(_Response([b"abc", b"def"])),
            ):
                result = download_staged_file(
                    "https://example.invalid/asset.bin",
                    destination,
                    max_bytes=6,
                )

            self.assertEqual(result.size_bytes, 6)
            self.assertEqual(destination.read_bytes(), b"abcdef")

    def test_stream_larger_than_declared_length_is_rejected_and_removed(self) -> None:
        self._assert_download_fails_and_is_removed(
            _Response([b"abc", b"def"], content_length="3"),
            max_bytes=12,
            error="declared Content-Length",
        )

    def test_stream_shorter_than_declared_length_is_rejected_and_removed(self) -> None:
        self._assert_download_fails_and_is_removed(
            _Response([b"abc"], content_length="6"),
            max_bytes=12,
            error="does not match Content-Length",
        )

    def test_missing_length_stream_cannot_exceed_limit(self) -> None:
        self._assert_download_fails_and_is_removed(
            _Response([b"abcd", b"efgh"]),
            max_bytes=7,
            error="configured size limit",
        )

    def test_invalid_content_length_is_rejected_before_file_creation(self) -> None:
        self._assert_download_fails_and_is_removed(
            _Response([b"abc"], content_length="not-a-number"),
            max_bytes=8,
            error="invalid Content-Length",
        )

    def test_hash_mismatch_is_rejected_and_removed(self) -> None:
        self._assert_download_fails_and_is_removed(
            _Response([b"abc"], content_length="3"),
            max_bytes=8,
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
            error="SHA-256",
        )

    def test_trusted_size_must_match_content_length(self) -> None:
        self._assert_download_fails_and_is_removed(
            _Response([b"abc"], content_length="3"),
            max_bytes=8,
            expected_size=4,
            error="trusted asset manifest",
        )

    def _assert_download_fails_and_is_removed(
        self,
        response: _Response,
        *,
        max_bytes: int,
        error: str,
        expected_sha256: str = "",
        expected_size: int | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            destination = Path(temp_name) / "asset.bin"
            with patch(
                "utils.download_integrity.open_response",
                return_value=nullcontext(response),
            ):
                with self.assertRaisesRegex(DownloadIntegrityError, error):
                    download_staged_file(
                        "https://example.invalid/asset.bin",
                        destination,
                        max_bytes=max_bytes,
                        expected_sha256=expected_sha256,
                        expected_size=expected_size,
                    )

            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
