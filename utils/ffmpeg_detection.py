from __future__ import annotations

import os
import platform
import subprocess


def detect_video_device_names() -> list[str]:
    if os.name != "nt":
        return []
    output = run_powershell_lines(
        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"
    )
    return [line for line in output if line]


def detect_cpu_name() -> str:
    if os.name == "nt":
        output = run_powershell_lines(
            "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name"
        )
        for line in output:
            if line:
                return line
    for key in ("PROCESSOR_IDENTIFIER", "PROCESSOR_ARCHITECTURE"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    detected = platform.processor().strip()
    return detected or "CPU"


def run_powershell_lines(command: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = decode_process_output(completed.stdout)
    return [line.strip() for line in text.splitlines() if line.strip()]


def pick_device(candidates: list[str], keywords: list[str]) -> str:
    lowered = [keyword.lower() for keyword in keywords]
    for candidate in candidates:
        source = candidate.lower()
        if all(keyword in source for keyword in lowered):
            return candidate
    for candidate in candidates:
        source = candidate.lower()
        if any(keyword in source for keyword in lowered):
            return candidate
    return ""


def decode_process_output(payload: bytes | None) -> str:
    if not payload:
        return ""
    for encoding in ("utf-8", "gb18030", "shift_jis"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")
