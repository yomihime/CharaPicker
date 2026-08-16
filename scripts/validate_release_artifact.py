#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


ROOT_DIR = Path(__file__).resolve().parents[1]
ARCHIVE_NAME_PATTERN = re.compile(
    r"^CharaPicker-v(?P<version>\d+\.\d+\.\d+)"
    r"(?P<suffix>-(?:alpha|beta|rc)(?:\.\d+)?|-local)?-windows-x64\.zip$"
)
CHECKSUM_PATTERN = re.compile(r"^(?P<digest>[0-9a-fA-F]{64})\s{2}(?P<name>[^\r\n]+)\r?\n?$")
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"(?i)(?:^|[\s\"'])(?:[a-z]:[\\/])")
UNIX_PRIVATE_PATH_PATTERN = re.compile(r"(?:^|[\s\"'])(?:/home/|/users/|/root/)", re.IGNORECASE)
REQUIRED_PACKAGE_FILES = {
    "CharaPicker/CharaPicker.exe",
    "CharaPicker/CharaPickerUpdater.exe",
    "CharaPicker/README.md",
    "CharaPicker/LICENSE",
    "CharaPicker/THIRD_PARTY_NOTICES.md",
}
REQUIRED_LOCALES = ("zh_CN", "zh_TW", "en_US", "ja_JP")
REQUIRED_RESOURCE_NAMES = ("default_prompts.json", "runtime_downloads.json", "app_icon.png")
FORBIDDEN_ROOT_NAMES = {
    ".codex",
    ".git",
    "bin",
    "build",
    "dist",
    "log",
    "models",
    "projects",
    "release",
}
FORBIDDEN_FILE_NAMES = {
    ".env",
    "config.yaml",
    "config.yaml.bak",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
}
FORBIDDEN_PRIVATE_SUFFIXES = (".bak", ".key", ".p12", ".pfx")
MAX_ARCHIVE_MEMBERS = 20000
MAX_UNCOMPRESSED_SIZE = 2 * 1024 * 1024 * 1024


def _sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return _sha256_stream(handle)


def _member_is_forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    parts = [part.casefold() for part in path.parts]
    if len(parts) < 2 or parts[0] != "charapicker":
        return True
    relative_parts = parts[1:]
    if relative_parts and relative_parts[0] in FORBIDDEN_ROOT_NAMES:
        return True
    if ".git" in relative_parts or ".codex" in relative_parts:
        return True
    filename = relative_parts[-1] if relative_parts else ""
    return filename in FORBIDDEN_FILE_NAMES or filename.endswith(FORBIDDEN_PRIVATE_SUFFIXES)


def _validate_member_name(name: str) -> str | None:
    if "\\" in name:
        return f"ZIP member uses a backslash path: {name}"
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return f"ZIP member has an unsafe path: {name}"
    if not path.parts or path.parts[0] != "CharaPicker":
        return f"ZIP member is outside the CharaPicker root: {name}"
    return None


def _validate_archive_contents(
    archive: zipfile.ZipFile,
) -> tuple[list[str], list[dict[str, str | int]]]:
    errors: list[str] = []
    infos = archive.infolist()
    if not infos:
        return ["release archive is empty"], []
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        errors.append(f"release archive has too many members: {len(infos)}")
    total_size = sum(info.file_size for info in infos)
    if total_size > MAX_UNCOMPRESSED_SIZE:
        errors.append(f"release archive is too large when unpacked: {total_size}")

    member_names: list[str] = []
    package_files: list[dict[str, str | int]] = []
    seen_casefolded: set[str] = set()
    timestamps: set[tuple[int, int, int, int, int, int]] = set()
    for info in infos:
        name = info.filename
        error = _validate_member_name(name)
        if error:
            errors.append(error)
        normalized = name.casefold()
        if normalized in seen_casefolded:
            errors.append(f"release archive contains a duplicate Windows path: {name}")
        seen_casefolded.add(normalized)
        if info.flag_bits & 0x1:
            errors.append(f"release archive contains an encrypted member: {name}")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            errors.append(f"release archive contains a symbolic link: {name}")
        if _member_is_forbidden(name):
            errors.append(f"release archive contains a forbidden path: {name}")
        if info.is_dir():
            continue

        member_names.append(name)
        timestamps.add(info.date_time)
        with archive.open(info, "r") as handle:
            digest = _sha256_stream(handle)
        package_files.append({"path": name, "size": info.file_size, "sha256": digest})

    if member_names != sorted(member_names, key=lambda name: (name.casefold(), name)):
        errors.append("release archive members are not stored in deterministic order")
    if len(timestamps) > 1:
        errors.append("release archive members do not share one normalized timestamp")

    names = set(member_names)
    missing_files = sorted(REQUIRED_PACKAGE_FILES - names)
    for missing in missing_files:
        errors.append(f"release archive is missing required file: {missing}")
    if not any(name.startswith("CharaPicker/_internal/") for name in names):
        errors.append("release archive is missing the PyInstaller _internal directory")
    for locale in REQUIRED_LOCALES:
        suffix = f"/i18n/{locale}.json"
        if not any(name.endswith(suffix) for name in names):
            errors.append(f"release archive is missing locale resource: {locale}")
    for resource_name in REQUIRED_RESOURCE_NAMES:
        suffix = f"/res/{resource_name}"
        if not any(name.endswith(suffix) for name in names):
            errors.append(f"release archive is missing runtime resource: {resource_name}")
    return errors, sorted(package_files, key=lambda item: str(item["path"]))


def _validate_checksum(
    archive_path: Path,
    checksum_path: Path,
    archive_digest: str,
) -> list[str]:
    if not checksum_path.is_file():
        return [f"release checksum is missing: {checksum_path.name}"]
    try:
        content = checksum_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return [f"release checksum is not readable ASCII: {checksum_path.name}"]
    match = CHECKSUM_PATTERN.fullmatch(content)
    if not match:
        return [f"release checksum has invalid syntax: {checksum_path.name}"]
    errors: list[str] = []
    if match.group("name") != archive_path.name:
        errors.append(
            f"release checksum names the wrong archive: {match.group('name')} != {archive_path.name}"
        )
    if match.group("digest").lower() != archive_digest:
        errors.append("release checksum does not match the archive SHA-256")
    return errors


def _manifest_contains_private_path(payload: Any) -> bool:
    if isinstance(payload, dict):
        return any(_manifest_contains_private_path(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_manifest_contains_private_path(value) for value in payload)
    if not isinstance(payload, str):
        return False
    return bool(
        WINDOWS_ABSOLUTE_PATH_PATTERN.search(payload)
        or UNIX_PRIVATE_PATH_PATTERN.search(payload)
    )


def _compare_package_manifest(
    declared_files: Any,
    actual_files: list[dict[str, str | int]],
) -> list[str]:
    if not isinstance(declared_files, list):
        return ["build-info package.files must be a list"]
    declared_by_path = {
        str(item.get("path")): item for item in declared_files if isinstance(item, dict)
    }
    actual_by_path = {str(item["path"]): item for item in actual_files}
    errors: list[str] = []
    missing = sorted(actual_by_path.keys() - declared_by_path.keys())
    extra = sorted(declared_by_path.keys() - actual_by_path.keys())
    if missing:
        errors.append(f"build-info package manifest is missing files: {missing}")
    if extra:
        errors.append(f"build-info package manifest has extra files: {extra}")
    for path in sorted(actual_by_path.keys() & declared_by_path.keys()):
        actual = actual_by_path[path]
        declared = declared_by_path[path]
        if declared.get("size") != actual["size"]:
            errors.append(f"build-info size mismatch for {path}")
        if declared.get("sha256") != actual["sha256"]:
            errors.append(f"build-info SHA-256 mismatch for {path}")
    return errors


def _validate_build_info(
    *,
    build_info_path: Path,
    archive_path: Path,
    checksum_path: Path,
    dependency_inventory_path: Path,
    archive_digest: str,
    actual_files: list[dict[str, str | int]],
    repository_root: Path,
) -> list[str]:
    if not build_info_path.is_file():
        return [f"build-info is missing: {build_info_path.name}"]
    try:
        payload = json.loads(build_info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"build-info is invalid JSON: {build_info_path.name}"]
    if not isinstance(payload, dict):
        return ["build-info root must be an object"]

    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("build-info schema_version must be 1")
    if _manifest_contains_private_path(payload):
        errors.append("build-info contains an absolute user or build path")

    name_match = ARCHIVE_NAME_PATTERN.fullmatch(archive_path.name)
    if not name_match:
        errors.append(f"release archive name is invalid: {archive_path.name}")
        archive_version_tag = ""
    else:
        archive_version_tag = name_match.group("version") + (name_match.group("suffix") or "")

    application = payload.get("application") if isinstance(payload.get("application"), dict) else {}
    if application.get("version_tag") != archive_version_tag:
        errors.append(
            "build-info version tag does not match archive name: "
            f"manifest={application.get('version_tag')} archive={archive_version_tag}"
        )

    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if source.get("repository") != "yomihime/CharaPicker":
        errors.append("build-info source repository is not the official repository")
    if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit") or "")):
        errors.append("build-info source commit must be a full lowercase SHA")
    if not isinstance(source.get("source_date_epoch"), int) or source.get("source_date_epoch", 0) <= 0:
        errors.append("build-info source_date_epoch must be a positive integer")
    source_tag = source.get("tag")
    if source_tag and str(source_tag).removeprefix("v") not in {
        archive_version_tag,
        f"{application.get('version')}-release",
    }:
        errors.append("build-info source tag does not match the packaged version")

    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    if target.get("platform") != "windows" or target.get("architecture") != "x64":
        errors.append("build-info target must be windows x64")
    toolchain = payload.get("toolchain") if isinstance(payload.get("toolchain"), dict) else {}
    if application.get("stage") != "local" and toolchain.get("python") != target.get("python"):
        errors.append("build-info Python toolchain does not match the release target")

    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    archive_info = artifacts.get("archive") if isinstance(artifacts.get("archive"), dict) else {}
    if archive_info.get("name") != archive_path.name:
        errors.append("build-info archive name does not match the artifact")
    if archive_info.get("size") != archive_path.stat().st_size:
        errors.append("build-info archive size does not match the artifact")
    if archive_info.get("sha256") != archive_digest:
        errors.append("build-info archive SHA-256 does not match the artifact")

    checksum_info = artifacts.get("checksum") if isinstance(artifacts.get("checksum"), dict) else {}
    if checksum_info.get("name") != checksum_path.name:
        errors.append("build-info checksum name does not match the artifact")
    if checksum_path.is_file():
        if checksum_info.get("size") != checksum_path.stat().st_size:
            errors.append("build-info checksum size does not match the artifact")
        if checksum_info.get("sha256") != sha256_file(checksum_path):
            errors.append("build-info checksum SHA-256 does not match the artifact")

    package = payload.get("package") if isinstance(payload.get("package"), dict) else {}
    if package.get("root") != "CharaPicker":
        errors.append("build-info package root must be CharaPicker")
    if package.get("file_count") != len(actual_files):
        errors.append("build-info package file_count does not match the archive")
    errors.extend(_compare_package_manifest(package.get("files"), actual_files))

    release_lock = (
        payload.get("release_lock") if isinstance(payload.get("release_lock"), dict) else {}
    )
    lock_name = str(release_lock.get("file") or "")
    lock_path = repository_root / lock_name
    if not lock_name or Path(lock_name).name != lock_name or not lock_path.is_file():
        errors.append("build-info release lock is missing from the repository")
    elif release_lock.get("sha256") != sha256_file(lock_path):
        errors.append("build-info release lock SHA-256 does not match the repository")
    if release_lock.get("hash_checking") is not True:
        errors.append("build-info must record release lock hash checking")

    inventory_info = (
        payload.get("dependency_inventory")
        if isinstance(payload.get("dependency_inventory"), dict)
        else {}
    )
    if inventory_info.get("file") != dependency_inventory_path.name:
        errors.append("build-info dependency inventory name does not match the artifact")
    if not dependency_inventory_path.is_file():
        errors.append(f"release dependency inventory is missing: {dependency_inventory_path.name}")
    else:
        try:
            inventory = json.loads(dependency_inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append("release dependency inventory is invalid JSON")
        else:
            if not isinstance(inventory, dict) or inventory.get("schema_version") != 1:
                errors.append("release dependency inventory schema_version must be 1")
            if _manifest_contains_private_path(inventory):
                errors.append("release dependency inventory contains an absolute private path")
            packages = inventory.get("packages") if isinstance(inventory, dict) else None
            if not isinstance(packages, list):
                errors.append("release dependency inventory packages must be a list")
            elif inventory_info.get("package_count") != len(packages):
                errors.append("build-info dependency inventory package count does not match")
            inventory_lock = inventory.get("release_lock", {})
            if not isinstance(inventory_lock, dict) or inventory_lock.get("sha256") != release_lock.get(
                "sha256"
            ):
                errors.append("release dependency inventory lock hash does not match build-info")
        if inventory_info.get("sha256") != sha256_file(dependency_inventory_path):
            errors.append("build-info dependency inventory SHA-256 does not match the artifact")

        target_config_path = repository_root / "release-environment.json"
        try:
            target_config = json.loads(target_config_path.read_text(encoding="utf-8"))
            source_inventory_path = repository_root / str(target_config["dependency_inventory"])
        except (OSError, KeyError, json.JSONDecodeError, TypeError):
            errors.append("repository release environment does not name a dependency inventory")
        else:
            if not source_inventory_path.is_file():
                errors.append("repository release dependency inventory is missing")
            elif sha256_file(source_inventory_path) != sha256_file(dependency_inventory_path):
                errors.append("published dependency inventory differs from the repository source")

    trust = payload.get("trust") if isinstance(payload.get("trust"), dict) else {}
    errors.extend(_validate_trust(trust, artifacts))
    return errors


def _validate_trust(trust: dict[str, Any], artifacts: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in (
        "signature_inspection_passed",
        "signed",
        "signature_verified",
        "attestation_generated",
    ):
        if not isinstance(trust.get(key), bool):
            errors.append(f"build-info trust.{key} must be a boolean")
    if trust.get("signature_policy") != "unsigned":
        errors.append("build-info trust.signature_policy must be unsigned")
    if trust.get("signature_inspection_passed") is not True:
        errors.append("build-info must record successful executable signature inspection")
    if trust.get("signed") is not False or trust.get("signature_verified") is not False:
        errors.append("unsigned release cannot claim an Authenticode signature")

    raw_entries = trust.get("executables")
    if not isinstance(raw_entries, list):
        errors.append("build-info trust.executables must be a list")
    else:
        expected = {
            "CharaPicker.exe": artifacts.get("main_executable", {}),
            "CharaPickerUpdater.exe": artifacts.get("updater_executable", {}),
        }
        seen: set[str] = set()
        for entry in raw_entries:
            if not isinstance(entry, dict):
                errors.append("build-info trust.executables contains an invalid entry")
                continue
            name = str(entry.get("name") or "")
            artifact = expected.get(name)
            if artifact is None or name in seen:
                errors.append(f"build-info trust contains an unexpected executable: {name}")
                continue
            seen.add(name)
            if entry.get("sha256") != artifact.get("sha256"):
                errors.append(f"build-info trust executable hash mismatch: {name}")
            if (
                entry.get("status") != "NotSigned"
                or entry.get("signed") is not False
                or entry.get("signature_verified") is not False
                or entry.get("signer_subject") is not None
                or entry.get("timestamp_subject") is not None
            ):
                errors.append(f"build-info trust contradicts unsigned policy: {name}")
        missing = sorted(set(expected) - seen)
        if missing:
            errors.append(f"build-info trust is missing executable status: {missing}")

    attested = trust.get("attestation_generated")
    if attested:
        if trust.get("attestation_provider") != "github":
            errors.append("build-info attestation provider must be github")
        if not str(trust.get("attestation_id") or "").isdigit():
            errors.append("build-info attestation ID is invalid")
        attestation_url = str(trust.get("attestation_url") or "")
        url_match = re.fullmatch(
            r"https://github\.com/[^/]+/[^/]+/attestations/(?P<id>\d+)",
            attestation_url,
        )
        if url_match is None or url_match.group("id") != str(trust.get("attestation_id")):
            errors.append("build-info attestation URL is invalid")
    elif any(
        trust.get(key) is not None
        for key in ("attestation_provider", "attestation_id", "attestation_url")
    ):
        errors.append("build-info cannot record attestation details before generation")
    return errors


def validate_release_artifact(
    archive_path: Path,
    *,
    checksum_path: Path | None = None,
    build_info_path: Path | None = None,
    dependency_inventory_path: Path | None = None,
    repository_root: Path = ROOT_DIR,
) -> list[str]:
    archive_path = archive_path.resolve()
    checksum_path = (checksum_path or archive_path.with_name(f"{archive_path.name}.sha256")).resolve()
    build_info_path = (build_info_path or archive_path.parent / "build-info.json").resolve()
    dependency_inventory_path = (
        dependency_inventory_path or archive_path.parent / "dependency-inventory.json"
    ).resolve()
    if not archive_path.is_file():
        return [f"release archive is missing: {archive_path}"]

    errors: list[str] = []
    if not ARCHIVE_NAME_PATTERN.fullmatch(archive_path.name):
        errors.append(f"release archive name is invalid: {archive_path.name}")
    archive_digest = sha256_file(archive_path)
    errors.extend(_validate_checksum(archive_path, checksum_path, archive_digest))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive_errors, actual_files = _validate_archive_contents(archive)
    except (OSError, zipfile.BadZipFile):
        return [*errors, f"release archive is not a readable ZIP: {archive_path.name}"]
    errors.extend(archive_errors)
    errors.extend(
        _validate_build_info(
            build_info_path=build_info_path,
            archive_path=archive_path,
            checksum_path=checksum_path,
            dependency_inventory_path=dependency_inventory_path,
            archive_digest=archive_digest,
            actual_files=actual_files,
            repository_root=repository_root.resolve(),
        )
    )
    return errors


def run_packaged_health_check(archive_path: Path) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="CharaPicker 健康检查 ") as tmp:
        temp_root = Path(tmp)
        install_root = temp_root / "安装 包"
        working_directory = temp_root / "启动 工作目录"
        install_root.mkdir()
        working_directory.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(install_root)
        executable = install_root / "CharaPicker" / "CharaPicker.exe"
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            completed = subprocess.run(
                [str(executable), "--health-check"],
                cwd=working_directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [f"packaged health check could not run: {type(exc).__name__}: {exc}"]
        if completed.returncode != 0:
            output = (completed.stdout + completed.stderr).strip()
            errors.append(
                f"packaged health check failed with exit code {completed.returncode}: {output}"
            )

        package_root = install_root / "CharaPicker"
        for relative in ("config.yaml", "projects", "log", "bin", "models"):
            if (package_root / relative).exists():
                errors.append(f"packaged health check created user/runtime data: {relative}")
        if any(working_directory.iterdir()):
            errors.append("packaged health check wrote files to its working directory")
    return errors


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a packaged CharaPicker release.")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--checksum", type=Path)
    parser.add_argument("--build-info", type=Path)
    parser.add_argument("--dependency-inventory", type=Path)
    parser.add_argument("--run-health-check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    if ns.archive is None:
        print("release artifact validation requires --archive and runs after packaging")
        return 0
    errors = validate_release_artifact(
        ns.archive,
        checksum_path=ns.checksum,
        build_info_path=ns.build_info,
        dependency_inventory_path=ns.dependency_inventory,
    )
    if not errors and ns.run_health_check:
        errors.extend(run_packaged_health_check(ns.archive.resolve()))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"release artifact validation passed: {ns.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
