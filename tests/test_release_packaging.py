from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_release import build_release_package, sha256_file


class ReleasePackagingTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        stage_dir = root / "CharaPicker"
        for relative, content in {
            "CharaPicker.exe": b"main-executable",
            "CharaPickerUpdater.exe": b"updater-executable",
            "README.md": b"readme",
            "LICENSE": b"license",
            "THIRD_PARTY_NOTICES.md": b"notices",
            "_internal/runtime.dll": b"runtime",
        }.items():
            path = stage_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        lock_path = root / "release-lock.txt"
        lock_path.write_text(
            "example==1.0 --hash=sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )
        inventory_path = root / "release-dependency-inventory.json"
        inventory_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "release_lock": {
                        "file": lock_path.name,
                        "sha256": sha256_file(lock_path),
                    },
                    "packages": [{"name": "example", "version": "1.0"}],
                }
            ),
            encoding="utf-8",
        )
        target_config = root / "release-environment.json"
        target_config.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "platform": "windows",
                    "architecture": "x64",
                    "runner": "windows-2022",
                    "python": "3.12.10",
                    "lock_file": str(lock_path),
                    "dependency_inventory": str(inventory_path),
                    "pyinstaller": "6.20.0",
                    "ruff": "0.15.12",
                    "python_hash_seed": "0",
                    "zip_compression": "deflate-9",
                }
            ),
            encoding="utf-8",
        )
        return stage_dir, target_config

    def _build(self, root: Path) -> tuple[Path, Path, dict]:
        stage_dir, target_config = self._fixture(root)
        archive = root / "release" / "CharaPicker-v1.0.0-rc-windows-x64.zip"
        build_info = root / "release" / "build-info.json"
        payload = build_release_package(
            stage_dir=stage_dir,
            archive_path=archive,
            build_info_path=build_info,
            target_config_path=target_config,
            version="1.0.0",
            stage="rc",
            version_tag="1.0.0-rc",
            tag="v1.0.0-rc",
            platform_tag="windows",
            architecture="x64",
            source_date_epoch=1700000000,
            commit="a" * 40,
            require_lock_match=False,
        )
        return archive, build_info, payload

    def test_normalized_archive_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            first_archive, _, _ = self._build(Path(first_tmp))
            second_archive, _, _ = self._build(Path(second_tmp))

            self.assertEqual(sha256_file(first_archive), sha256_file(second_archive))

    def test_build_info_uses_relative_paths_and_source_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive, build_info, payload = self._build(Path(tmp))

            serialized = build_info.read_text(encoding="utf-8")
            self.assertNotIn(str(Path(tmp).resolve()), serialized)
            self.assertEqual(payload["source"]["source_date_epoch"], 1700000000)
            self.assertEqual(payload["package"]["root"], "CharaPicker")
            self.assertEqual(payload["artifacts"]["archive"]["sha256"], sha256_file(archive))
            checksum = archive.with_name(f"{archive.name}.sha256")
            self.assertTrue(checksum.is_file())
            self.assertEqual(
                checksum.read_text(encoding="ascii"),
                f"{sha256_file(archive)}  {archive.name}\n",
            )
            published_inventory = archive.parent / "dependency-inventory.json"
            self.assertTrue(published_inventory.is_file())
            self.assertEqual(
                payload["dependency_inventory"]["sha256"],
                sha256_file(published_inventory),
            )

            with zipfile.ZipFile(archive) as packaged:
                names = packaged.namelist()
                self.assertTrue(names)
                self.assertTrue(all(name.startswith("CharaPicker/") for name in names))
                self.assertEqual(len({info.date_time for info in packaged.infolist()}), 1)


if __name__ == "__main__":
    unittest.main()
