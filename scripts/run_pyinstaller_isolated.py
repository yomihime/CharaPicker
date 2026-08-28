#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ntpath
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping


ROOT_DIR = Path(__file__).resolve().parents[1]


def _environment_value(environment: Mapping[str, str], name: str) -> str:
    expected = name.casefold()
    return next(
        (value for key, value in environment.items() if key.casefold() == expected),
        "",
    )


def _deduplicate_windows_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        cleaned = path.strip().strip('"')
        if not cleaned:
            continue
        normalized = ntpath.normcase(ntpath.normpath(cleaned))
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
    return result


def isolated_pyinstaller_path(
    environment: Mapping[str, str],
    *,
    python_executable: str,
    base_executable: str,
    base_prefix: str,
) -> str:
    system_root = _environment_value(environment, "SystemRoot") or _environment_value(
        environment, "WINDIR"
    )
    candidates = [
        ntpath.dirname(python_executable),
        ntpath.dirname(base_executable),
        base_prefix,
        ntpath.join(base_prefix, "Scripts"),
    ]
    if system_root:
        candidates.extend(
            [
                ntpath.join(system_root, "System32"),
                system_root,
                ntpath.join(system_root, "System32", "Wbem"),
            ]
        )
    return ";".join(_deduplicate_windows_paths(candidates))


def pyinstaller_environment(
    environment: Mapping[str, str] | None = None,
    *,
    python_executable: str | None = None,
    base_executable: str | None = None,
    base_prefix: str | None = None,
) -> dict[str, str]:
    child_environment = {
        key: value
        for key, value in (environment or os.environ).items()
        if key.casefold() != "path"
    }
    executable = python_executable or sys.executable
    resolved_base_executable = base_executable or getattr(sys, "_base_executable", executable)
    resolved_base_prefix = base_prefix or sys.base_prefix
    child_environment["PATH"] = isolated_pyinstaller_path(
        child_environment,
        python_executable=executable,
        base_executable=resolved_base_executable,
        base_prefix=resolved_base_prefix,
    )
    return child_environment


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PyInstaller without inheriting host PATH DLL search directories."
    )
    parser.add_argument("spec", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    completed = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ns.spec)],
        cwd=ROOT_DIR,
        env=pyinstaller_environment(),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
