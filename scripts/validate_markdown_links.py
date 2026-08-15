#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT_DIR = Path(__file__).resolve().parents[1]
INLINE_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(\s*(?P<target><[^>]+>|[^)\s]+)")
REFERENCE_LINK_PATTERN = re.compile(
    r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)",
    re.MULTILINE,
)
FENCE_PATTERN = re.compile(r"^\s*(?:```|~~~)")


def tracked_markdown_files(root: Path = ROOT_DIR) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return sorted(
        root / item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _targets_outside_fences(content: str) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    in_fence = False
    for line_number, line in enumerate(content.splitlines(), 1):
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for pattern in (INLINE_LINK_PATTERN, REFERENCE_LINK_PATTERN):
            for match in pattern.finditer(line):
                targets.append((line_number, match.group("target")))
    return targets


def _relative_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith(("#", "//")):
        return None
    parsed = urlsplit(target)
    if parsed.scheme:
        return None
    return unquote(parsed.path)


def validate_markdown_links(
    files: list[Path] | None = None,
    *,
    root: Path = ROOT_DIR,
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for path in files if files is not None else tracked_markdown_files(root):
        content = path.read_text(encoding="utf-8")
        for line_number, raw_target in _targets_outside_fences(content):
            relative_target = _relative_target(raw_target)
            if relative_target is None:
                continue
            resolved = (path.parent / relative_target).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                errors.append(
                    f"{path.relative_to(root).as_posix()}:{line_number}: "
                    f"relative link escapes the repository: {raw_target}"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"{path.relative_to(root).as_posix()}:{line_number}: "
                    f"relative link target does not exist: {raw_target}"
                )
    return errors


def main() -> int:
    errors = validate_markdown_links()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Markdown relative link validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
