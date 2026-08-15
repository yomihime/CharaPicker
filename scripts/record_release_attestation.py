#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ATTESTATION_URL_PATTERN = re.compile(
    r"https://github\.com/(?P<owner>[^/]+)/(?P<repository>[^/]+)/attestations/(?P<id>\d+)"
)


class ReleaseAttestationError(RuntimeError):
    pass


def record_release_attestation(
    payload: dict[str, Any],
    *,
    attestation_id: str,
    attestation_url: str,
) -> dict[str, Any]:
    normalized_id = attestation_id.strip()
    normalized_url = attestation_url.strip()
    match = ATTESTATION_URL_PATTERN.fullmatch(normalized_url)
    if not normalized_id.isdigit() or match is None or match.group("id") != normalized_id:
        raise ReleaseAttestationError("GitHub attestation ID and URL do not match")
    source = payload.get("source")
    repository = source.get("repository") if isinstance(source, dict) else None
    attested_repository = f"{match.group('owner')}/{match.group('repository')}"
    if not isinstance(repository, str) or repository.casefold() != attested_repository.casefold():
        raise ReleaseAttestationError("GitHub attestation repository does not match build-info")

    trust = payload.get("trust")
    if not isinstance(trust, dict):
        raise ReleaseAttestationError("build-info has no trust record")
    if (
        trust.get("signature_policy") != "unsigned"
        or trust.get("signature_inspection_passed") is not True
        or trust.get("signed") is not False
        or trust.get("signature_verified") is not False
    ):
        raise ReleaseAttestationError("build-info signature status is not a verified unsigned baseline")
    if trust.get("attestation_generated") is not False:
        raise ReleaseAttestationError("build-info already records an attestation")
    if any(
        trust.get(key) is not None
        for key in ("attestation_provider", "attestation_id", "attestation_url")
    ):
        raise ReleaseAttestationError("build-info contains premature attestation details")

    updated = json.loads(json.dumps(payload))
    updated_trust = updated["trust"]
    updated_trust["attestation_generated"] = True
    updated_trust["attestation_provider"] = "github"
    updated_trust["attestation_id"] = normalized_id
    updated_trust["attestation_url"] = normalized_url
    return updated


def write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.attestation.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record GitHub provenance in build-info.json.")
    parser.add_argument("--build-info", type=Path, required=True)
    parser.add_argument("--attestation-id", required=True)
    parser.add_argument("--attestation-url", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    try:
        payload = json.loads(ns.build_info.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ReleaseAttestationError("build-info root must be an object")
        updated = record_release_attestation(
            payload,
            attestation_id=ns.attestation_id,
            attestation_url=ns.attestation_url,
        )
        write_json_atomically(ns.build_info, updated)
    except (OSError, json.JSONDecodeError, ReleaseAttestationError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"release attestation recorded: {updated['trust']['attestation_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
