from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.env_manager import find_llamacpp_binary, find_whisper_runtime_binary
from utils.ffmpeg_downloader import download_and_install_ffmpeg
from utils.ffmpeg_tool import find_ffmpeg_binary
from utils.llamacpp_downloader import download_and_install_llamacpp
from utils.runtime_layout import (
    FFMPEG_DIRECTORY_NAME,
    LLAMACPP_DIRECTORY_NAME,
    managed_runtime_install_dir,
)


class RuntimeDiscoveryTests(unittest.TestCase):
    def test_managed_directories_take_priority_over_legacy_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bin_root = Path(temp_name) / "bin"
            managed_ffmpeg = bin_root / "ffmpeg" / "9.0.1" / "win-x64" / "bin" / "ffmpeg.exe"
            newer_managed_ffmpeg = (
                bin_root / "ffmpeg" / "10.0.0" / "win-x64" / "bin" / "ffmpeg.exe"
            )
            legacy_ffmpeg = bin_root / "ffmpeg-8.1-build" / "bin" / "ffmpeg.exe"
            managed_whisper = (
                bin_root
                / "whisper.cpp"
                / "v1.9.2"
                / "win-x64-cpu"
                / "Release"
                / "whisper-cli.exe"
            )
            legacy_whisper = bin_root / "whisper.cpp-v1.8.4-x64" / "Release" / "whisper-cli.exe"
            for path in (
                managed_ffmpeg,
                newer_managed_ffmpeg,
                legacy_ffmpeg,
                managed_whisper,
                legacy_whisper,
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            self.assertEqual(find_ffmpeg_binary(bin_root), newer_managed_ffmpeg)
            self.assertEqual(find_whisper_runtime_binary(bin_root), managed_whisper)

    def test_llamacpp_discovery_does_not_cross_into_whisper_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bin_root = Path(temp_name) / "bin"
            whisper_main = bin_root / "whisper.cpp" / "v1" / "win-x64" / "main.exe"
            whisper_main.parent.mkdir(parents=True)
            whisper_main.touch()

            self.assertIsNone(find_llamacpp_binary(bin_root))

            managed_llama = bin_root / "llama.cpp" / "b10446" / "win-x64-cpu" / "llama-cli.exe"
            managed_llama.parent.mkdir(parents=True)
            managed_llama.touch()
            self.assertEqual(find_llamacpp_binary(bin_root), managed_llama)

    def test_root_level_legacy_binaries_remain_discoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bin_root = Path(temp_name) / "bin"
            bin_root.mkdir()
            legacy_ffmpeg = bin_root / "ffmpeg.exe"
            legacy_llama = bin_root / "llama-cli.exe"
            legacy_ffmpeg.touch()
            legacy_llama.touch()

            self.assertEqual(find_ffmpeg_binary(bin_root), legacy_ffmpeg)
            self.assertEqual(find_llamacpp_binary(bin_root), legacy_llama)

    def test_ambiguous_root_main_binary_is_not_assigned_to_a_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bin_root = Path(temp_name) / "bin"
            bin_root.mkdir()
            (bin_root / "main.exe").touch()

            self.assertIsNone(find_llamacpp_binary(bin_root))
            self.assertIsNone(find_whisper_runtime_binary(bin_root))


class RuntimeDownloaderLayoutTests(unittest.TestCase):
    def test_ffmpeg_installs_into_versioned_tool_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bin_root = Path(temp_name) / "bin"
            asset = _runtime_asset("9.0.1", "ffmpeg.zip")
            expected_root = managed_runtime_install_dir(
                bin_root,
                FFMPEG_DIRECTORY_NAME,
                "9.0.1",
                "win-x64",
            )
            expected_root.mkdir(parents=True)
            (expected_root / "stale.dll").touch()

            with (
                patch("utils.ffmpeg_downloader.runtime_download_asset", return_value=asset),
                patch(
                    "utils.ffmpeg_downloader.download_staged_file",
                    side_effect=lambda _url, target, **_kwargs: _write_zip(
                        target,
                        "ffmpeg-build/bin/ffmpeg.exe",
                    ),
                ),
                patch(
                    "utils.ffmpeg_downloader.find_usable_ffmpeg_binary",
                    side_effect=lambda root: _find_binary(root, "ffmpeg.exe"),
                ),
            ):
                binary = download_and_install_ffmpeg(bin_root=bin_root)

            self.assertTrue(binary.is_relative_to(expected_root))
            self.assertTrue(binary.is_file())
            self.assertFalse((expected_root / "stale.dll").exists())
            self.assertFalse(expected_root.with_name("win-x64.backup").exists())
            self.assertEqual(list((bin_root / "ffmpeg").glob(".staging-*")), [])

    def test_llamacpp_installs_into_versioned_tool_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bin_root = Path(temp_name) / "bin"
            asset = _runtime_asset("b10446", "llama.zip")

            with (
                patch("utils.llamacpp_downloader.runtime_download_asset", return_value=asset),
                patch(
                    "utils.llamacpp_downloader.download_staged_file",
                    side_effect=lambda _url, target, **_kwargs: _write_zip(
                        target,
                        "llama-cli.exe",
                    ),
                ),
                patch(
                    "utils.llamacpp_downloader.find_usable_llamacpp_binary",
                    side_effect=lambda root: _find_binary(root, "llama-cli.exe"),
                ),
            ):
                binary = download_and_install_llamacpp(bin_root=bin_root)

            expected_root = managed_runtime_install_dir(
                bin_root,
                LLAMACPP_DIRECTORY_NAME,
                "b10446",
                "win-x64-cpu",
            )
            self.assertTrue(binary.is_relative_to(expected_root))
            self.assertTrue(binary.is_file())
            self.assertEqual(list((bin_root / "llama.cpp").glob(".staging-*")), [])


def _runtime_asset(version: str, file_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        version=version,
        file_name=file_name,
        url=f"https://example.invalid/{file_name}",
        max_bytes=1024,
        size_bytes=1,
        sha256="0" * 64,
    )


def _write_zip(target: Path, member_name: str) -> None:
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(member_name, b"runtime")


def _find_binary(root: Path, file_name: str) -> Path | None:
    return next((path for path in root.rglob(file_name) if path.is_file()), None)


if __name__ == "__main__":
    unittest.main()
