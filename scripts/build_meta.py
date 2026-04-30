#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
from dataclasses import dataclass


DEFAULT_VERSION = "0.1.0"
DEFAULT_STAGE = "release"
ALLOWED_STAGES = {"alpha", "beta", "rc", "release", "local"}
STAGE_WITH_INDEX_PATTERN = re.compile(r"^(alpha|beta|rc)\.\d+$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class Meta:
    version: str
    stage: str
    platform_tag: str
    arch_tag: str
    local_build: int
    raw_tag: str
    tag_source: str


def _normalize_platform(system_name: str) -> str:
    value = system_name.strip().lower()
    if value.startswith("win"):
        return "windows"
    if value.startswith("linux"):
        return "linux"
    if value.startswith("darwin") or value.startswith("mac"):
        return "macos"
    return value or "unknown"


def _normalize_arch(machine_name: str) -> str:
    value = machine_name.strip().lower()
    if value in {"amd64", "x86_64", "x64"}:
        return "x64"
    if value in {"x86", "i386", "i686"}:
        return "x86"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    return value or "unknown"


def _run_git_describe(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "describe", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def _parse_tag(tag: str) -> tuple[str, str]:
    tag_value = tag.strip()
    if tag_value.lower().startswith("v"):
        tag_value = tag_value[1:]
    if "-" not in tag_value:
        return tag_value, DEFAULT_STAGE
    version, stage = tag_value.split("-", 1)
    return version, stage


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--version")
    parser.add_argument("--stage")
    parser.add_argument("--platform")
    parser.add_argument("--arch")
    parser.add_argument("--tag")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("extra", nargs="*")
    return parser.parse_args(argv)


def _build_meta(ns: argparse.Namespace) -> Meta:
    platform_tag = _normalize_platform(ns.platform or platform.system())
    arch_tag = _normalize_arch(ns.arch or platform.machine())

    raw_tag = ""
    tag_source = ""
    if ns.tag:
        raw_tag = ns.tag
        tag_source = "cli"
    else:
        exact = _run_git_describe(["--tags", "--exact-match"])
        if exact:
            raw_tag = exact
            tag_source = "exact"
        else:
            nearest = _run_git_describe(["--tags", "--abbrev=0"])
            if nearest:
                raw_tag = nearest
                tag_source = "nearest"

    version = DEFAULT_VERSION
    stage = DEFAULT_STAGE

    if raw_tag:
        parsed_version, parsed_stage = _parse_tag(raw_tag)
        if parsed_version:
            version = parsed_version
        if parsed_stage:
            stage = parsed_stage

    if ns.version:
        version = ns.version
    if ns.stage:
        stage = ns.stage

    local_build = 1 if ns.local or any(item.lower() == "local" for item in ns.extra) else 0
    if local_build:
        stage = "local"

    return Meta(
        version=version,
        stage=stage,
        platform_tag=platform_tag,
        arch_tag=arch_tag,
        local_build=local_build,
        raw_tag=raw_tag,
        tag_source=tag_source,
    )


def _validate(meta: Meta) -> list[str]:
    errors: list[str] = []
    if not SEMVER_PATTERN.fullmatch(meta.version):
        errors.append(f"VERSION must match x.y.z, got: {meta.version}")
    stage = meta.stage.lower()
    if stage not in ALLOWED_STAGES and not STAGE_WITH_INDEX_PATTERN.fullmatch(stage):
        errors.append(
            "STAGE must be one of alpha/beta/rc/release/local "
            f"or alpha.N/beta.N/rc.N, got: {meta.stage}"
        )
    return errors


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    meta = _build_meta(ns)
    errors = _validate(meta)
    if errors:
        for line in errors:
            print(f"ERROR={line}")
        return 1

    print(f"VERSION={meta.version}")
    print(f"STAGE={meta.stage}")
    print(f"PLATFORM_TAG={meta.platform_tag}")
    print(f"ARCH_TAG={meta.arch_tag}")
    print(f"LOCAL_BUILD={meta.local_build}")
    print(f"RAW_TAG={meta.raw_tag}")
    print(f"TAG_SOURCE={meta.tag_source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
