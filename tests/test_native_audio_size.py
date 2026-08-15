from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.ai_model_middleware import (
    NativeAudioRequestTooLargeError,
    _openai_audio_reference_to_data,
    _read_openai_inline_audio_bytes,
)


class NativeAudioSizeTests(unittest.TestCase):
    def test_small_local_audio_is_encoded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "voice.wav"
            content = b"RIFF-small-audio"
            audio_path.write_bytes(content)

            data_uri, audio_format = _openai_audio_reference_to_data(str(audio_path))

        self.assertEqual(audio_format, "wav")
        self.assertEqual(data_uri, f"data:;base64,{base64.b64encode(content).decode('ascii')}")

    def test_oversized_audio_is_rejected_before_opening_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "oversized.wav"
            audio_path.write_bytes(b"012345678")

            with patch.object(Path, "open", side_effect=AssertionError("must not open")):
                with self.assertRaises(NativeAudioRequestTooLargeError) as context:
                    _read_openai_inline_audio_bytes(audio_path, max_bytes=8)

        self.assertEqual(context.exception.size_bytes, 9)
        self.assertEqual(context.exception.max_bytes, 8)
        self.assertEqual(context.exception.failure_category, "unsupported_capability")

    def test_exact_limit_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "boundary.wav"
            audio_path.write_bytes(b"12345678")

            content = _read_openai_inline_audio_bytes(audio_path, max_bytes=8)

        self.assertEqual(content, b"12345678")


if __name__ == "__main__":
    unittest.main()
