from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.runtime_downloads import (
    RuntimeDownloadManifestError,
    load_runtime_download_manifest,
)


EXPECTED_RUNTIME_ASSETS = {
    "ffmpeg-win-x64",
    "whispercpp-win-x64-cpu",
    "whispercpp-win-x64-blas",
    "whispercpp-win-x64-cuda",
    "llamacpp-win-x64-cpu",
    "whisper-model-tiny",
    "whisper-model-base",
    "whisper-model-small",
}


class RuntimeDownloadManifestTests(unittest.TestCase):
    def test_repository_manifest_pins_runtime_assets(self) -> None:
        manifest = load_runtime_download_manifest()

        self.assertEqual(set(manifest.assets), EXPECTED_RUNTIME_ASSETS)
        for asset in manifest.assets.values():
            self.assertGreater(asset.size_bytes, 0)
            self.assertGreaterEqual(asset.max_bytes, asset.size_bytes)
            self.assertNotIn("/latest/", asset.url.casefold())
            self.assertNotIn("/main/", asset.url.casefold())

    def test_unpinned_runtime_url_is_rejected(self) -> None:
        payload = {
            "schema_version": 1,
            "assets": {
                "unsafe": {
                    "version": "latest",
                    "file_name": "runtime.zip",
                    "url": "https://github.com/example/project/releases/download/latest/runtime.zip",
                    "sha256": "a" * 64,
                    "size_bytes": 10,
                    "max_bytes": 20,
                    "source_revision": "latest",
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "runtime_downloads.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(RuntimeDownloadManifestError):
                load_runtime_download_manifest(path)

    def test_runtime_hash_and_size_policy_are_required(self) -> None:
        payload = {
            "schema_version": 1,
            "assets": {
                "unsafe": {
                    "version": "v1",
                    "file_name": "runtime.zip",
                    "url": "https://github.com/example/project/releases/download/v1/runtime.zip",
                    "sha256": "missing",
                    "size_bytes": 30,
                    "max_bytes": 20,
                    "source_revision": "v1",
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "runtime_downloads.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(RuntimeDownloadManifestError):
                load_runtime_download_manifest(path)


if __name__ == "__main__":
    unittest.main()
