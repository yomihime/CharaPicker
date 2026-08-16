from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_release import build_release_package, sha256_file
from scripts.validate_release_artifact import validate_release_artifact


class ReleaseArtifactTests(unittest.TestCase):
    def _build_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        stage = root / "CharaPicker"
        files = {
            "CharaPicker.exe": b"main-executable",
            "CharaPickerUpdater.exe": b"updater-executable",
            "README.md": b"readme",
            "LICENSE": b"license",
            "THIRD_PARTY_NOTICES.md": b"notices",
            "_internal/runtime.dll": b"runtime",
            "_internal/res/default_prompts.json": b"{}",
            "_internal/res/runtime_downloads.json": b"{}",
            "_internal/res/app_icon.png": b"png",
        }
        for locale in ("zh_CN", "zh_TW", "en_US", "ja_JP"):
            files[f"_internal/i18n/{locale}.json"] = b"{}"
        for relative, content in files.items():
            path = stage / relative
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

        release = root / "release"
        archive = release / "CharaPicker-v1.0.0-local-windows-x64.zip"
        build_info = release / "build-info.json"
        signature_report = release / "signature-report.json"
        signature_report.parent.mkdir(parents=True, exist_ok=True)
        signature_report.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy": "unsigned",
                    "inspection_passed": True,
                    "executables": [
                        {
                            "name": name,
                            "sha256": sha256_file(stage / name),
                            "status": "NotSigned",
                            "signed": False,
                            "signature_verified": False,
                            "signer_subject": None,
                            "timestamp_subject": None,
                        }
                        for name in ("CharaPicker.exe", "CharaPickerUpdater.exe")
                    ],
                }
            ),
            encoding="utf-8",
        )
        build_release_package(
            stage_dir=stage,
            archive_path=archive,
            build_info_path=build_info,
            signature_report_path=signature_report,
            target_config_path=target_config,
            version="1.0.0",
            stage="local",
            version_tag="1.0.0-local",
            tag="",
            platform_tag="windows",
            architecture="x64",
            source_date_epoch=1700000000,
            commit="a" * 40,
            require_lock_match=False,
        )
        return archive, archive.with_name(f"{archive.name}.sha256"), build_info

    def test_valid_release_artifact_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum, build_info = self._build_fixture(root)

            errors = validate_release_artifact(
                archive,
                checksum_path=checksum,
                build_info_path=build_info,
                repository_root=root,
            )

            self.assertEqual(errors, [])

    def test_checksum_tampering_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum, build_info = self._build_fixture(root)
            checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")

            errors = validate_release_artifact(
                archive,
                checksum_path=checksum,
                build_info_path=build_info,
                repository_root=root,
            )

            self.assertTrue(any("checksum does not match" in error for error in errors))

    def test_forbidden_runtime_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum, build_info = self._build_fixture(root)
            with zipfile.ZipFile(archive, "a") as packaged:
                packaged.writestr("CharaPicker/projects/private/config.json", b"private")
                packaged.writestr("CharaPicker/_internal/card.json.bak", b"private backup")
            checksum.write_text(f"{sha256_file(archive)}  {archive.name}\n", encoding="ascii")

            errors = validate_release_artifact(
                archive,
                checksum_path=checksum,
                build_info_path=build_info,
                repository_root=root,
            )

            self.assertTrue(any("forbidden path" in error for error in errors))
            self.assertTrue(any("card.json.bak" in error for error in errors))

    def test_missing_required_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum, build_info = self._build_fixture(root)
            rewritten = archive.with_suffix(".rewritten.zip")
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rewritten, "w") as target:
                for info in source.infolist():
                    if info.filename != "CharaPicker/LICENSE":
                        target.writestr(info, source.read(info))
            rewritten.replace(archive)
            checksum.write_text(f"{sha256_file(archive)}  {archive.name}\n", encoding="ascii")

            errors = validate_release_artifact(
                archive,
                checksum_path=checksum,
                build_info_path=build_info,
                repository_root=root,
            )

            self.assertTrue(any("missing required file: CharaPicker/LICENSE" in error for error in errors))

    def test_unsigned_trust_claim_must_match_executable_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum, build_info = self._build_fixture(root)
            payload = json.loads(build_info.read_text(encoding="utf-8"))
            payload["trust"]["executables"][0]["signed"] = True
            payload["trust"]["executables"][0]["status"] = "Valid"
            build_info.write_text(json.dumps(payload), encoding="utf-8")

            errors = validate_release_artifact(
                archive,
                checksum_path=checksum,
                build_info_path=build_info,
                repository_root=root,
            )

            self.assertTrue(any("contradicts unsigned policy" in error for error in errors))

    def test_attested_release_requires_valid_github_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum, build_info = self._build_fixture(root)
            payload = json.loads(build_info.read_text(encoding="utf-8"))
            payload["trust"].update(
                {
                    "attestation_generated": True,
                    "attestation_provider": "github",
                    "attestation_id": "12345",
                    "attestation_url": (
                        "https://github.com/yomihime/CharaPicker/attestations/67890"
                    ),
                }
            )
            build_info.write_text(json.dumps(payload), encoding="utf-8")

            errors = validate_release_artifact(
                archive,
                checksum_path=checksum,
                build_info_path=build_info,
                repository_root=root,
            )

            self.assertTrue(any("attestation URL is invalid" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
