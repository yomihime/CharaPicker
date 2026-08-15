#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_CONFIG = ROOT_DIR / "release-environment.json"
ZIP_MIN_EPOCH = 315532800  # 1980-01-01T00:00:00Z
LOCK_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+"
    r"--hash=sha256:(?P<digest>[0-9a-f]{64})$"
)
REQUIRED_PACKAGE_FILES = (
    "CharaPicker.exe",
    "CharaPickerUpdater.exe",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_target_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "platform",
        "architecture",
        "runner",
        "python",
        "lock_file",
        "pyinstaller",
        "ruff",
        "python_hash_seed",
        "zip_compression",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"release environment is missing keys: {missing}")
    return payload


def parse_release_lock(path: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        match = LOCK_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(f"invalid release lock entry at {path.name}:{line_number}")
        entries.append(match.groupdict())
    if not entries:
        raise ValueError(f"release lock has no packages: {path.name}")
    return entries


def canonicalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def collect_dependency_inventory(
    lock_entries: list[dict[str, str]],
    *,
    require_lock_match: bool,
) -> list[dict[str, str | None]]:
    installed = {
        canonicalize_package_name(distribution.metadata["Name"]): distribution.version
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    inventory: list[dict[str, str | None]] = []
    mismatches: list[str] = []
    for entry in lock_entries:
        installed_version = installed.get(canonicalize_package_name(entry["name"]))
        inventory.append(
            {
                "name": entry["name"],
                "locked_version": entry["version"],
                "installed_version": installed_version,
            }
        )
        if installed_version != entry["version"]:
            mismatches.append(
                f"{entry['name']}: locked={entry['version']} installed={installed_version or 'missing'}"
            )
    if require_lock_match and mismatches:
        raise RuntimeError("release environment does not match lock:\n" + "\n".join(mismatches))
    return inventory


def validate_release_environment(
    target: dict[str, Any],
    *,
    platform_tag: str,
    architecture: str,
) -> None:
    actual = {
        "platform": platform_tag,
        "architecture": architecture,
        "python": platform.python_version(),
        "pyinstaller": importlib.metadata.version("pyinstaller"),
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
    }
    mismatches = [
        f"{key}: expected={target[key]} actual={value or 'missing'}"
        for key, value in actual.items()
        if str(target[key]) != str(value)
    ]
    if mismatches:
        raise RuntimeError("release toolchain does not match target:\n" + "\n".join(mismatches))


def collect_package_files(stage_dir: Path) -> list[dict[str, str | int]]:
    files: list[dict[str, str | int]] = []
    root_name = stage_dir.name
    for path in _sorted_stage_files(stage_dir):
        relative = path.relative_to(stage_dir).as_posix()
        files.append(
            {
                "path": f"{root_name}/{relative}",
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return files


def _sorted_stage_files(stage_dir: Path) -> list[Path]:
    return sorted(
        (item for item in stage_dir.rglob("*") if item.is_file()),
        key=lambda item: (
            item.relative_to(stage_dir).as_posix().casefold(),
            item.relative_to(stage_dir).as_posix(),
        ),
    )


def validate_stage(stage_dir: Path) -> None:
    if stage_dir.name != "CharaPicker":
        raise ValueError(f"release stage directory must be named CharaPicker: {stage_dir}")
    for relative in REQUIRED_PACKAGE_FILES:
        if not (stage_dir / relative).is_file():
            raise FileNotFoundError(f"required release file is missing: {relative}")
    for relative in ("_internal",):
        if not (stage_dir / relative).is_dir():
            raise FileNotFoundError(f"required release directory is missing: {relative}")


def normalized_zip_timestamp(source_date_epoch: int) -> tuple[int, int, int, int, int, int]:
    stamp = time.gmtime(max(source_date_epoch, ZIP_MIN_EPOCH))
    return (
        stamp.tm_year,
        stamp.tm_mon,
        stamp.tm_mday,
        stamp.tm_hour,
        stamp.tm_min,
        stamp.tm_sec - stamp.tm_sec % 2,
    )


def write_normalized_zip(stage_dir: Path, archive_path: Path, source_date_epoch: int) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = normalized_zip_timestamp(source_date_epoch)
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in _sorted_stage_files(stage_dir):
            relative = path.relative_to(stage_dir).as_posix()
            info = zipfile.ZipInfo(f"{stage_dir.name}/{relative}", date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def _command_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            list(args),
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def _package_file(files: list[dict[str, str | int]], relative: str) -> dict[str, str | int]:
    expected = f"CharaPicker/{relative}"
    for item in files:
        if item["path"] == expected:
            return item
    raise FileNotFoundError(f"required package artifact is missing: {expected}")


def build_release_package(
    *,
    stage_dir: Path,
    archive_path: Path,
    build_info_path: Path,
    target_config_path: Path,
    version: str,
    stage: str,
    version_tag: str,
    tag: str,
    platform_tag: str,
    architecture: str,
    source_date_epoch: int,
    commit: str,
    require_lock_match: bool,
) -> dict[str, Any]:
    stage_dir = stage_dir.resolve()
    archive_path = archive_path.resolve()
    build_info_path = build_info_path.resolve()
    target_config_path = target_config_path.resolve()
    validate_stage(stage_dir)

    target = load_target_config(target_config_path)
    if require_lock_match:
        validate_release_environment(
            target,
            platform_tag=platform_tag,
            architecture=architecture,
        )
    lock_path = ROOT_DIR / str(target["lock_file"])
    lock_entries = parse_release_lock(lock_path)
    dependencies = collect_dependency_inventory(
        lock_entries,
        require_lock_match=require_lock_match,
    )

    package_files = collect_package_files(stage_dir)
    write_normalized_zip(stage_dir, archive_path, source_date_epoch)
    archive_digest = sha256_file(archive_path)
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    checksum_path.write_text(f"{archive_digest}  {archive_path.name}\n", encoding="ascii")

    commit_sha = commit or os.environ.get("GITHUB_SHA", "") or _command_output(
        "git", "rev-parse", "HEAD"
    )
    source_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(source_date_epoch))
    main_executable = _package_file(package_files, "CharaPicker.exe")
    updater_executable = _package_file(package_files, "CharaPickerUpdater.exe")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "application": {
            "name": "CharaPicker",
            "version": version,
            "stage": stage,
            "version_tag": version_tag,
        },
        "source": {
            "commit": commit_sha,
            "tag": tag or None,
            "source_date_epoch": source_date_epoch,
            "source_date_utc": source_utc,
        },
        "target": {
            "platform": platform_tag,
            "architecture": architecture,
            "runner": target["runner"],
            "python": target["python"],
        },
        "runner": {
            "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
            "architecture": os.environ.get("RUNNER_ARCH") or architecture,
        },
        "toolchain": {
            "python": platform.python_version(),
            "pip": importlib.metadata.version("pip"),
            "pyinstaller": importlib.metadata.version("pyinstaller"),
            "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        },
        "release_lock": {
            "file": lock_path.name,
            "sha256": sha256_file(lock_path),
            "hash_checking": True,
        },
        "dependencies": dependencies,
        "package": {
            "root": stage_dir.name,
            "file_count": len(package_files),
            "files": package_files,
        },
        "artifacts": {
            "main_executable": main_executable,
            "updater_executable": updater_executable,
            "archive": {
                "name": archive_path.name,
                "size": archive_path.stat().st_size,
                "sha256": archive_digest,
            },
            "checksum": {
                "name": checksum_path.name,
                "size": checksum_path.stat().st_size,
                "sha256": sha256_file(checksum_path),
            },
        },
        "trust": {
            "signed": False,
            "signature_verified": False,
            "attestation_generated": False,
        },
    }
    build_info_path.parent.mkdir(parents=True, exist_ok=True)
    build_info_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the normalized CharaPicker release archive.")
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--build-info", type=Path, required=True)
    parser.add_argument("--target-config", type=Path, default=DEFAULT_TARGET_CONFIG)
    parser.add_argument("--version", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--version-tag", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--platform", dest="platform_tag", required=True)
    parser.add_argument("--arch", dest="architecture", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--commit", default="")
    parser.add_argument("--require-lock-match", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    payload = build_release_package(
        stage_dir=ns.stage_dir,
        archive_path=ns.archive,
        build_info_path=ns.build_info,
        target_config_path=ns.target_config,
        version=ns.version,
        stage=ns.stage,
        version_tag=ns.version_tag,
        tag=ns.tag,
        platform_tag=ns.platform_tag,
        architecture=ns.architecture,
        source_date_epoch=ns.source_date_epoch,
        commit=ns.commit,
        require_lock_match=ns.require_lock_match,
    )
    print(json.dumps(payload["artifacts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
