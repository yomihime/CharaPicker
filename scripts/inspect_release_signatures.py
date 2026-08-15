#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


POWERSHELL_PATHS_ENV = "CHARAPICKER_SIGNATURE_PATHS_JSON"
POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$paths = ConvertFrom-Json $env:CHARAPICKER_SIGNATURE_PATHS_JSON
$result = foreach ($path in $paths) {
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    [pscustomobject]@{
        name = [IO.Path]::GetFileName($path)
        status = [string]$signature.Status
        signer_subject = if ($signature.SignerCertificate) {
            $signature.SignerCertificate.Subject
        } else {
            $null
        }
        timestamp_subject = if ($signature.TimeStamperCertificate) {
            $signature.TimeStamperCertificate.Subject
        } else {
            $null
        }
    }
}
$result | ConvertTo-Json -Compress
"""


class ReleaseSignatureError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_release_signatures(
    executables: list[Path],
    *,
    powershell: str = "powershell.exe",
) -> list[dict[str, Any]]:
    resolved = [path.resolve() for path in executables]
    if not resolved:
        raise ReleaseSignatureError("at least one release executable is required")
    missing = [path.name for path in resolved if not path.is_file()]
    if missing:
        raise ReleaseSignatureError(f"release executables are missing: {sorted(missing)}")

    environment = os.environ.copy()
    environment[POWERSHELL_PATHS_ENV] = json.dumps(
        [str(path) for path in resolved],
        ensure_ascii=True,
    )
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                POWERSHELL_SCRIPT,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseSignatureError("Authenticode inspection failed") from exc

    try:
        raw_payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseSignatureError("Authenticode inspection returned invalid JSON") from exc
    raw_entries = raw_payload if isinstance(raw_payload, list) else [raw_payload]
    if len(raw_entries) != len(resolved):
        raise ReleaseSignatureError("Authenticode inspection returned an unexpected file count")

    entries: list[dict[str, Any]] = []
    for path, raw_entry in zip(resolved, raw_entries, strict=True):
        if not isinstance(raw_entry, dict) or raw_entry.get("name") != path.name:
            raise ReleaseSignatureError("Authenticode inspection returned the wrong executable")
        status = str(raw_entry.get("status") or "")
        if not status:
            raise ReleaseSignatureError(f"Authenticode status is missing: {path.name}")
        entries.append(
            {
                "name": path.name,
                "sha256": sha256_file(path),
                "status": status,
                "signed": status != "NotSigned",
                "signature_verified": status == "Valid",
                "signer_subject": _optional_string(raw_entry.get("signer_subject")),
                "timestamp_subject": _optional_string(raw_entry.get("timestamp_subject")),
            }
        )
    return entries


def build_signature_report(entries: list[dict[str, Any]], *, expected: str) -> dict[str, Any]:
    if expected != "unsigned":
        raise ReleaseSignatureError(f"unsupported release signature policy: {expected}")
    unexpected = [entry["name"] for entry in entries if entry["status"] != "NotSigned"]
    if unexpected:
        raise ReleaseSignatureError(
            "unsigned release policy found signed or invalid executables: "
            f"{sorted(unexpected)}"
        )
    return {
        "schema_version": 1,
        "policy": "unsigned",
        "inspection_passed": True,
        "executables": entries,
    }


def _optional_string(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Windows release Authenticode status.")
    parser.add_argument("--executable", type=Path, action="append", required=True)
    parser.add_argument("--expect", choices=("unsigned",), required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    try:
        entries = inspect_release_signatures(ns.executable)
        report = build_signature_report(entries, expected=ns.expect)
    except ReleaseSignatureError as exc:
        print(f"ERROR: {exc}")
        return 1
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"release signature inspection passed: policy={report['policy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
