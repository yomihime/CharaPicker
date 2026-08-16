#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


OFFICIAL_REPOSITORY = "yomihime/CharaPicker"
ARCHIVE_PATTERN = re.compile(
    r"^CharaPicker-v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)(?:\.\d+)?)?-windows-x64\.zip$"
)


class ReleaseNotesError(RuntimeError):
    pass


def extract_changelog_section(text: str, *, tag: str) -> str:
    lines = text.splitlines()
    escaped_tag = re.escape(tag)
    heading = re.compile(rf"^##\s+\[?{escaped_tag}\]?(?:\s|$)")
    start = next((index for index, line in enumerate(lines) if heading.match(line)), None)
    if start is None:
        raise ReleaseNotesError(f"CHANGELOG.md has no section for {tag}")
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    body = "\n".join(lines[start + 1 : end]).strip()
    if not body:
        raise ReleaseNotesError(f"CHANGELOG.md section for {tag} is empty")
    return body


def release_trust_guidance(archive_name: str) -> str:
    if ARCHIVE_PATTERN.fullmatch(archive_name) is None:
        raise ReleaseNotesError(f"release archive name is invalid: {archive_name}")
    return f"""## 下载与信任说明

- 官方发布入口仅为 [GitHub Releases](https://github.com/{OFFICIAL_REPOSITORY}/releases)。
- 当前 Windows 二进制未使用 Authenticode 签名；Windows 可能显示未知发布者或信誉提示。
- 同名 `.sha256` 用于确认下载字节与本 Release 的 checksum 一致，不用于验证发布者身份。
- GitHub artifact attestation 用于确认产物由本仓库的 GitHub Actions 工作流生成；它不是 Windows 发布者签名，也不保证消除 SmartScreen 提示。

PowerShell 校验 SHA-256：

```powershell
$archive = ".\\{archive_name}"
$expected = ((Get-Content "$archive.sha256" -Raw).Trim() -split '\\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {{ throw "SHA-256 mismatch" }}
$actual
```

联网验证 GitHub 构建 provenance：

```powershell
gh attestation verify ".\\{archive_name}" -R {OFFICIAL_REPOSITORY}
```"""


def prepare_release_notes(changelog_text: str, *, tag: str, archive_name: str) -> str:
    changelog = extract_changelog_section(changelog_text, tag=tag)
    guidance = release_trust_guidance(archive_name)
    return f"{changelog}\n\n{guidance}\n"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare GitHub Release notes.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    try:
        if not ns.archive.is_file():
            raise ReleaseNotesError(f"release archive is missing: {ns.archive.name}")
        notes = prepare_release_notes(
            ns.changelog.read_text(encoding="utf-8"),
            tag=ns.tag,
            archive_name=ns.archive.name,
        )
        ns.output.write_text(notes, encoding="utf-8")
    except (OSError, ReleaseNotesError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"release notes prepared: {ns.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
