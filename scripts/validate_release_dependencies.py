#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCK_ENTRY_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+"
    r"--hash=sha256:(?P<digest>[0-9a-f]{64})$"
)
REQUIREMENT_NAME_PATTERN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)")
PROJECT_SECTION_PATTERN = re.compile(r"(?ms)^\[project\]\s*(?P<body>.*?)(?=^\[|\Z)")
DEPENDENCIES_PATTERN = re.compile(r"(?ms)^dependencies\s*=\s*\[(?P<body>.*?)\]")
QUOTED_VALUE_PATTERN = re.compile(r'"(?P<value>[^"]+)"')
BUILD_TOOL_NAMES = {"pip", "pyinstaller", "setuptools", "wheel"}
QUALITY_TOOL_NAMES = {"ruff"}
PRIVATE_PATH_PATTERN = re.compile(
    r"(?:[a-z]:[\\/]|/(?:home|users|root)/)",
    re.IGNORECASE,
)


def canonicalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_release_lock(path: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        match = LOCK_ENTRY_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(f"invalid release lock entry at {path.name}:{line_number}")
        entries.append(match.groupdict())
    return entries


def direct_requirements(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        match = REQUIREMENT_NAME_PATTERN.match(line)
        if not match:
            raise ValueError(f"unable to parse direct requirement: {line}")
        names.add(canonicalize_name(match.group("name")))
    return names


def pyproject_dependencies(path: Path) -> set[str]:
    content = path.read_text(encoding="utf-8")
    project = PROJECT_SECTION_PATTERN.search(content)
    dependencies = DEPENDENCIES_PATTERN.search(project.group("body") if project else "")
    if not dependencies:
        raise ValueError("pyproject.toml has no [project].dependencies array")
    names: set[str] = set()
    for match in QUOTED_VALUE_PATTERN.finditer(dependencies.group("body")):
        requirement = REQUIREMENT_NAME_PATTERN.match(match.group("value"))
        if requirement:
            names.add(canonicalize_name(requirement.group("name")))
    return names


def _installed_distributions() -> dict[str, importlib.metadata.Distribution]:
    return {
        canonicalize_name(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }


def _license_metadata(distribution: importlib.metadata.Distribution) -> tuple[str, list[str]]:
    expression = str(distribution.metadata.get("License-Expression") or "").strip()
    legacy = str(distribution.metadata.get("License") or "").strip()
    if not expression and legacy and "\n" not in legacy and len(legacy) <= 160:
        expression = legacy
    classifiers = sorted(
        value.removeprefix("License :: ")
        for value in distribution.metadata.get_all("Classifier", [])
        if value.startswith("License :: ")
    )
    return expression or "UNKNOWN", classifiers


def generate_inventory(root: Path = ROOT_DIR) -> dict[str, Any]:
    target = json.loads((root / "release-environment.json").read_text(encoding="utf-8"))
    lock_path = root / str(target["lock_file"])
    lock_entries = parse_release_lock(lock_path)
    runtime_names = direct_requirements(root / "requirements.txt")
    installed = _installed_distributions()
    packages: list[dict[str, Any]] = []
    mismatches: list[str] = []
    for entry in lock_entries:
        canonical_name = canonicalize_name(entry["name"])
        distribution = installed.get(canonical_name)
        if distribution is None or distribution.version != entry["version"]:
            mismatches.append(
                f"{entry['name']}: locked={entry['version']} "
                f"installed={distribution.version if distribution else 'missing'}"
            )
            continue
        license_value, license_classifiers = _license_metadata(distribution)
        roles: list[str] = []
        if canonical_name in runtime_names:
            roles.append("direct-runtime")
        if canonical_name in BUILD_TOOL_NAMES:
            roles.append("build-tool")
        if canonical_name in QUALITY_TOOL_NAMES:
            roles.append("quality-tool")
        if not roles:
            roles.append("transitive")
        packages.append(
            {
                "name": entry["name"],
                "version": entry["version"],
                "source": "PyPI",
                "roles": roles,
                "license": license_value,
                "license_classifiers": license_classifiers,
            }
        )
    if mismatches:
        raise RuntimeError("installed environment does not match release lock:\n" + "\n".join(mismatches))
    return {
        "schema_version": 1,
        "target": {
            "platform": target["platform"],
            "architecture": target["architecture"],
            "python": target["python"],
        },
        "release_lock": {
            "file": lock_path.name,
            "sha256": sha256_file(lock_path),
        },
        "packages": sorted(packages, key=lambda item: canonicalize_name(item["name"])),
        "legal_notice": (
            "Package metadata is an audit aid only; upstream license texts and legal review control."
        ),
    }


def validate_release_dependencies(
    root: Path = ROOT_DIR,
    *,
    verify_installed: bool = False,
) -> list[str]:
    errors: list[str] = []
    target = json.loads((root / "release-environment.json").read_text(encoding="utf-8"))
    lock_path = root / str(target["lock_file"])
    inventory_path = root / str(target["dependency_inventory"])
    lock_entries = parse_release_lock(lock_path)
    lock_versions = {
        canonicalize_name(entry["name"]): entry["version"] for entry in lock_entries
    }

    requirements_names = direct_requirements(root / "requirements.txt")
    project_names = pyproject_dependencies(root / "pyproject.toml")
    if requirements_names != project_names:
        errors.append(
            "direct dependency drift between requirements.txt and pyproject.toml: "
            f"requirements_only={sorted(requirements_names - project_names)} "
            f"pyproject_only={sorted(project_names - requirements_names)}"
        )
    missing_from_lock = sorted(requirements_names - lock_versions.keys())
    if missing_from_lock:
        errors.append(f"direct runtime dependencies are missing from release lock: {missing_from_lock}")

    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").casefold()
    for name in sorted(requirements_names | {"pyinstaller"}):
        if name.casefold() not in notices:
            errors.append(f"THIRD_PARTY_NOTICES.md does not mention direct dependency: {name}")

    if not inventory_path.is_file():
        return [*errors, f"release dependency inventory is missing: {inventory_path.name}"]
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [*errors, f"release dependency inventory is invalid JSON: {inventory_path.name}"]
    if inventory.get("schema_version") != 1:
        errors.append("release dependency inventory schema_version must be 1")
    if PRIVATE_PATH_PATTERN.search(json.dumps(inventory, ensure_ascii=False)):
        errors.append("release dependency inventory contains an absolute private path")
    if inventory.get("target") != {
        "platform": target["platform"],
        "architecture": target["architecture"],
        "python": target["python"],
    }:
        errors.append("release dependency inventory target does not match release environment")
    inventory_lock = inventory.get("release_lock", {})
    if inventory_lock.get("file") != lock_path.name:
        errors.append("release dependency inventory names the wrong lock file")
    if inventory_lock.get("sha256") != sha256_file(lock_path):
        errors.append("release dependency inventory lock SHA-256 is stale")

    package_entries = inventory.get("packages")
    if not isinstance(package_entries, list):
        return [*errors, "release dependency inventory packages must be a list"]
    inventory_versions: dict[str, str] = {}
    for package in package_entries:
        if not isinstance(package, dict):
            errors.append("release dependency inventory contains a non-object package entry")
            continue
        name = canonicalize_name(str(package.get("name") or ""))
        if not name:
            errors.append("release dependency inventory contains a package without a name")
            continue
        if name in inventory_versions:
            errors.append(f"release dependency inventory contains duplicate package: {name}")
        inventory_versions[name] = str(package.get("version") or "")
        if package.get("source") != "PyPI":
            errors.append(f"release dependency inventory has an unexpected source for {name}")
        if not isinstance(package.get("license"), str) or not package.get("license"):
            errors.append(f"release dependency inventory has no license metadata for {name}")
        if not isinstance(package.get("roles"), list) or not package.get("roles"):
            errors.append(f"release dependency inventory has no roles for {name}")
    if inventory_versions != lock_versions:
        errors.append(
            "release dependency inventory package versions differ from release lock: "
            f"inventory_only={sorted(inventory_versions.keys() - lock_versions.keys())} "
            f"lock_only={sorted(lock_versions.keys() - inventory_versions.keys())} "
            f"version_mismatches={sorted(name for name in inventory_versions.keys() & lock_versions.keys() if inventory_versions[name] != lock_versions[name])}"
        )

    if verify_installed:
        installed = {
            name: distribution.version for name, distribution in _installed_distributions().items()
        }
        mismatches = sorted(
            f"{name}: locked={version} installed={installed.get(name, 'missing')}"
            for name, version in lock_versions.items()
            if installed.get(name) != version
        )
        if mismatches:
            errors.append("installed dependency versions differ from release lock:\n" + "\n".join(mismatches))
    return errors


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the v1 release dependency inventory.")
    parser.add_argument("--verify-installed", action="store_true")
    parser.add_argument("--write", type=Path, help="Write inventory generated from the installed lock.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    if ns.write is not None:
        payload = generate_inventory()
        ns.write.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"release dependency inventory written: {ns.write}")
        return 0
    errors = validate_release_dependencies(verify_installed=ns.verify_installed)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("release dependency inventory validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
