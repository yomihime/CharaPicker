#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.build_meta import _build_meta, _parse_args, _validate  # noqa: E402
from utils.app_metadata import (  # noqa: E402
    APP_NAME,
    APP_RELEASE_STAGE,
    APP_VERSION,
    APP_VERSION_TAG,
)
from utils.app_update import UPDATE_ASSET_SUFFIX  # noqa: E402


ACTION_REF_PATTERN = re.compile(r"^\s*uses:\s*[^\s@]+@(?P<ref>[^\s#]+)", re.MULTILINE)
BATCH_DEFAULT_PATTERN = re.compile(r'^set "(?P<key>VERSION|STAGE|VERSION_TAG)=(?P<value>[^"]*)"$', re.MULTILINE)
PROJECT_SECTION_PATTERN = re.compile(r"(?ms)^\[project\]\s*(?P<body>.*?)(?=^\[|\Z)")
PROJECT_VERSION_PATTERN = re.compile(r'^version\s*=\s*"(?P<version>[^"]+)"', re.MULTILINE)
FORBIDDEN_TRACKED_PATHS = {
    "config.yaml",
    "config.yaml.bak",
}
FORBIDDEN_TRACKED_PREFIXES = (
    ".codex/",
    "build/",
    "dist/",
    "log/",
    "release/",
)
RUNTIME_ROOT_ALLOWLIST = {
    "bin/ARCHITECTURE.md",
    "models/ARCHITECTURE.md",
    "projects/ARCHITECTURE.md",
}
PRIVATE_FILE_SUFFIXES = (".bak", ".key", ".p12", ".pem", ".pfx")
FINAL_README_CONTRACTS = {
    "README.md": (
        "首个稳定基线",
        (("beta", "仍处在 beta 阶段"), ("RC", "当前处于 1.0 RC")),
    ),
    "docs/readme/README.zh_TW.md": (
        "首個穩定基線",
        (("beta", "仍處在 beta 階段"), ("RC", "目前處於 1.0 RC")),
    ),
    "docs/readme/README.en_US.md": (
        "first stable baseline",
        (("beta", "Still in beta"), ("RC", "Currently in the 1.0 RC")),
    ),
    "docs/readme/README.ja_JP.md": (
        "最初の安定版ベースライン",
        (("beta", "まだ beta 段階"), ("RC", "現在は 1.0 RC")),
    ),
}


def _read_project_version(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    section = PROJECT_SECTION_PATTERN.search(content)
    if not section:
        return ""
    match = PROJECT_VERSION_PATTERN.search(section.group("body"))
    return match.group("version") if match else ""


def _read_batch_defaults(path: Path) -> dict[str, str]:
    return {
        match.group("key"): match.group("value")
        for match in BATCH_DEFAULT_PATTERN.finditer(path.read_text(encoding="utf-8"))
    }


def _changelog_has_section(path: Path, version_tag: str) -> bool:
    expected = re.compile(rf"^##\s+\[?v{re.escape(version_tag)}\]?(?:\s|$)", re.MULTILINE)
    content = path.read_text(encoding="utf-8")
    match = expected.search(content)
    if not match:
        return False
    next_heading = re.search(r"^##\s+", content[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(content)
    return bool(content[match.end() : end].strip())


def _tracked_files(root: Path) -> set[str]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to inspect tracked repository paths") from exc
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    }


def _validate_tracked_paths(tracked: set[str]) -> list[str]:
    errors: list[str] = []
    for path in sorted(tracked):
        lowered = path.lower()
        if path in FORBIDDEN_TRACKED_PATHS or path.startswith(FORBIDDEN_TRACKED_PREFIXES):
            errors.append(f"runtime/private path must not be tracked: {path}")
        if (
            path.startswith(("bin/", "models/", "projects/"))
            and path not in RUNTIME_ROOT_ALLOWLIST
        ):
            errors.append(f"runtime data path must not be tracked: {path}")
        if lowered.endswith(PRIVATE_FILE_SUFFIXES):
            errors.append(f"private key or certificate file must not be tracked: {path}")
    return errors


def _validate_final_readmes(root: Path) -> list[str]:
    errors: list[str] = []
    for relative, (required_marker, forbidden_markers) in FINAL_README_CONTRACTS.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"final release README is missing: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        if required_marker.casefold() not in content.casefold():
            errors.append(f"final release status marker is missing from {relative}: {required_marker}")
        for stage, forbidden_marker in forbidden_markers:
            if forbidden_marker.casefold() in content.casefold():
                errors.append(
                    f"stale {stage} status remains in {relative}: {forbidden_marker}"
                )
    return errors


def validate_repository(
    root: Path = ROOT_DIR,
    *,
    tag: str | None = None,
    tracked_files: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    requested_tag = (tag or f"v{APP_VERSION_TAG}").strip()
    meta = _build_meta(
        _parse_args(
            [
                f"--tag={requested_tag}",
                "--platform=windows",
                "--arch=x64",
            ]
        )
    )
    errors.extend(f"tag/source metadata: {message}" for message in _validate(meta))

    project_version = _read_project_version(root / "pyproject.toml")
    if project_version != APP_VERSION:
        errors.append(
            f"pyproject.toml version mismatch: project={project_version or 'missing'} app={APP_VERSION}"
        )

    batch_defaults = _read_batch_defaults(root / "build.bat")
    expected_batch = {
        "VERSION": APP_VERSION,
        "STAGE": APP_RELEASE_STAGE,
        "VERSION_TAG": APP_VERSION_TAG,
    }
    for key, expected in expected_batch.items():
        actual = batch_defaults.get(key)
        if actual != expected:
            errors.append(f"build.bat {key} mismatch: build={actual or 'missing'} app={expected}")

    changelog = root / "CHANGELOG.md"
    if not _changelog_has_section(changelog, meta.version_tag):
        errors.append(f"CHANGELOG.md has no non-empty version heading for v{meta.version_tag}")

    target_path = root / "release-environment.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))
    workflow_path = root / ".github" / "workflows" / "build.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    for expected in (
        f"runs-on: {target['runner']}",
        f'python-version: "{target["python"]}"',
        str(target["lock_file"]),
    ):
        if expected not in workflow:
            errors.append(f"build workflow does not use release target value: {expected}")

    action_refs = [match.group("ref") for match in ACTION_REF_PATTERN.finditer(workflow)]
    if not action_refs:
        errors.append("build workflow contains no action references")
    for action_ref in action_refs:
        if not re.fullmatch(r"[0-9a-f]{40}", action_ref):
            errors.append(f"build workflow action is not pinned to a full commit SHA: {action_ref}")
    if workflow.count("contents: write") != 1:
        errors.append("build workflow must grant contents: write to exactly one publish job")
    if workflow.count("id-token: write") != 1 or workflow.count("attestations: write") != 1:
        errors.append("build workflow must isolate attestation permissions to one job")
    if any(
        dependency not in workflow
        for dependency in ("needs: quality", "needs: windows-build", "needs: attest-release")
    ):
        errors.append(
            "build workflow release jobs do not form quality -> build -> attest -> publish chain"
        )
    if "scripts/prepare_release_notes.py" not in workflow:
        errors.append("build workflow does not generate release trust guidance")

    lock_path = root / str(target["lock_file"])
    if not lock_path.is_file():
        errors.append(f"release lock file is missing: {target['lock_file']}")
    expected_suffix = f"{target['platform']}-{target['architecture']}.zip"
    if UPDATE_ASSET_SUFFIX != expected_suffix:
        errors.append(
            "update asset suffix does not match release target: "
            f"updater={UPDATE_ASSET_SUFFIX} target={expected_suffix}"
        )
    expected_archive = f"{APP_NAME}-v{meta.version_tag}-{expected_suffix}"
    if "%APP_NAME%-v%VERSION_TAG%-%PLATFORM_TAG%-%ARCH_TAG%.zip" not in (
        root / "build.bat"
    ).read_text(encoding="utf-8"):
        errors.append(f"build.bat does not compose the expected archive name: {expected_archive}")

    tracked = _tracked_files(root) if tracked_files is None else tracked_files
    errors.extend(_validate_tracked_paths(tracked))
    if meta.stage.lower() == "release":
        errors.extend(_validate_final_readmes(root))
    return errors


def _parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate source and release metadata consistency.")
    parser.add_argument("--tag", help="Release tag to validate; defaults to the current source version.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_cli(argv)
    tag = ns.tag
    if not tag and os.environ.get("GITHUB_REF_TYPE") == "tag":
        tag = os.environ.get("GITHUB_REF_NAME")
    errors = validate_repository(tag=tag)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"release readiness validation passed for {tag or f'v{APP_VERSION_TAG}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
