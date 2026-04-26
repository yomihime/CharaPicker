from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from core.models import SourceProcessingConfig, SourceProcessingPreset, SourceSegmentMode
from utils.env_manager import BIN_ROOT
from utils.paths import ensure_project_tree

FFMPEG_CANDIDATES = ("ffmpeg.exe", "ffmpeg")
FFMPEG_CHECK_TIMEOUT_SECONDS = 6
VIDEO_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".flv",
    ".wmv",
    ".m4v",
}
FFMPEG_CANCELLED_MESSAGE = "Source processing cancelled"
ProgressCallback = Callable[[int, int, str], None]
CancelledCallback = Callable[[], bool]


class FfmpegProcessError(RuntimeError):
    pass


def find_ffmpeg_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in FFMPEG_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file():
            return candidate
    for file_name in FFMPEG_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file():
                return candidate
    return None


def is_ffmpeg_binary_usable(binary_path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(binary_path), "-version"],
            cwd=binary_path.parent,
            capture_output=True,
            timeout=FFMPEG_CHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = _decode_process_output(completed.stdout)
    return completed.returncode == 0 and "ffmpeg" in output.lower()


def find_usable_ffmpeg_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in FFMPEG_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file() and is_ffmpeg_binary_usable(candidate):
            return candidate
    for file_name in FFMPEG_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file() and is_ffmpeg_binary_usable(candidate):
                return candidate
    return None


def has_ffmpeg_binary(bin_root: Path = BIN_ROOT) -> bool:
    return find_usable_ffmpeg_binary(bin_root) is not None


def process_raw_sources_with_ffmpeg(
    project_id: str,
    raw_sources: list[Path],
    processing_config: SourceProcessingConfig,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelledCallback | None = None,
) -> int:
    ffmpeg_binary = find_usable_ffmpeg_binary()
    if ffmpeg_binary is None:
        raise FfmpegProcessError("FFmpeg is unavailable.")
    if processing_config.preset == SourceProcessingPreset.ORIGINAL:
        raise FfmpegProcessError("FFmpeg processing requires a non-original preset.")

    paths = ensure_project_tree(project_id)
    raw_root = paths.raw
    materials_root = paths.materials
    total = len(raw_sources)
    if progress is not None:
        progress(0, total, "")

    processed_count = 0
    for index, source in enumerate(raw_sources, start=1):
        _raise_if_cancelled(cancelled)
        try:
            relative_path = source.resolve().relative_to(raw_root.resolve())
        except ValueError:
            continue
        target = materials_root / relative_path
        _remove_path(target)

        if _is_video_source(source):
            _process_video_with_ffmpeg(ffmpeg_binary, source, target, processing_config, cancelled=cancelled)
        else:
            _link_source(source, target)

        processed_count += 1
        if progress is not None:
            progress(index, total, relative_path.as_posix())
    return processed_count


def _process_video_with_ffmpeg(
    ffmpeg_binary: Path,
    source: Path,
    target: Path,
    config: SourceProcessingConfig,
    *,
    cancelled: CancelledCallback | None = None,
) -> None:
    target.mkdir(parents=True, exist_ok=True)

    if config.preset == SourceProcessingPreset.TRANSCODE_ONLY:
        output_path = target / "transcoded.mp4"
        command = _build_transcode_command(ffmpeg_binary, source, output_path, config)
        _run_ffmpeg_command(command, cancelled=cancelled)
        return

    segment_seconds = _segment_seconds(ffmpeg_binary, source, config, cancelled=cancelled)
    if segment_seconds <= 0:
        segment_seconds = 1.0

    if config.preset == SourceProcessingPreset.SEGMENT_ONLY:
        output_suffix = source.suffix.lower() if source.suffix else ".mp4"
        output_pattern = target / f"segment_%03d{output_suffix}"
        command = _build_segment_only_command(ffmpeg_binary, source, output_pattern, segment_seconds, config)
        _run_ffmpeg_command(command, cancelled=cancelled)
        return

    if config.preset == SourceProcessingPreset.SEGMENT_TRANSCODE:
        output_pattern = target / "segment_%03d.mp4"
        command = _build_segment_transcode_command(ffmpeg_binary, source, output_pattern, segment_seconds, config)
        _run_ffmpeg_command(command, cancelled=cancelled)
        return

    raise FfmpegProcessError(f"Unsupported preset: {config.preset}")


def _build_transcode_command(ffmpeg_binary: Path, source: Path, output_path: Path, config: SourceProcessingConfig) -> list[str]:
    command = _base_ffmpeg_command(ffmpeg_binary)
    command.extend(_input_seek_args(source, config))
    command.extend(_effective_trim_duration_args(ffmpeg_binary, source, config))
    command.extend(_transcode_args(config))
    command.append(str(output_path))
    return command


def _build_segment_only_command(
    ffmpeg_binary: Path,
    source: Path,
    output_pattern: Path,
    segment_seconds: float,
    config: SourceProcessingConfig,
) -> list[str]:
    command = _base_ffmpeg_command(ffmpeg_binary)
    command.extend(_input_seek_args(source, config))
    command.extend(_effective_trim_duration_args(ffmpeg_binary, source, config))
    command.extend(["-c", "copy"])
    command.extend(
        [
            "-f",
            "segment",
            "-reset_timestamps",
            "1",
            "-segment_time",
            _format_ffmpeg_number(segment_seconds),
            str(output_pattern),
        ]
    )
    return command


def _build_segment_transcode_command(
    ffmpeg_binary: Path,
    source: Path,
    output_pattern: Path,
    segment_seconds: float,
    config: SourceProcessingConfig,
) -> list[str]:
    command = _base_ffmpeg_command(ffmpeg_binary)
    command.extend(_input_seek_args(source, config))
    command.extend(_effective_trim_duration_args(ffmpeg_binary, source, config))
    command.extend(_transcode_args(config))
    command.extend(
        [
            "-f",
            "segment",
            "-reset_timestamps",
            "1",
            "-segment_time",
            _format_ffmpeg_number(segment_seconds),
            str(output_pattern),
        ]
    )
    return command


def _base_ffmpeg_command(ffmpeg_binary: Path) -> list[str]:
    return [str(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-y"]


def _input_seek_args(source: Path, config: SourceProcessingConfig) -> list[str]:
    args = ["-i", str(source)]
    if config.trim_enabled:
        trim_start_seconds = _mmss_to_seconds(config.trim_start)
        if trim_start_seconds > 0:
            args.extend(["-ss", _format_hhmmss(trim_start_seconds)])
    return args


def _effective_trim_duration_args(ffmpeg_binary: Path, source: Path, config: SourceProcessingConfig) -> list[str]:
    if not config.trim_enabled:
        return []
    trim_start_seconds = _mmss_to_seconds(config.trim_start)
    trim_end_seconds = _mmss_to_seconds(config.trim_end)
    if trim_start_seconds <= 0 and trim_end_seconds <= 0:
        return []
    duration = _probe_duration_seconds(ffmpeg_binary, source)
    effective_duration = duration - trim_start_seconds - trim_end_seconds
    if effective_duration <= 0:
        raise FfmpegProcessError(f"Trim range is invalid for source: {source}")
    return ["-t", _format_ffmpeg_number(effective_duration)]


def _transcode_args(config: SourceProcessingConfig) -> list[str]:
    codec = "libx264" if config.codec.upper() == "H.264" else "libx265"
    args = ["-c:v", codec, "-c:a", "aac", "-movflags", "+faststart"]
    resolution = config.resolution.lower()
    if resolution == "540p":
        args.extend(["-vf", "scale=-2:540"])
    elif resolution == "720p":
        args.extend(["-vf", "scale=-2:720"])
    elif resolution == "1080p":
        args.extend(["-vf", "scale=-2:1080"])
    return args


def _segment_seconds(
    ffmpeg_binary: Path,
    source: Path,
    config: SourceProcessingConfig,
    *,
    cancelled: CancelledCallback | None = None,
) -> float:
    if config.segment_mode == SourceSegmentMode.TIME:
        return max(_hhmmss_to_seconds(config.segment_time), 1.0)

    duration = _effective_duration_seconds(ffmpeg_binary, source, config, cancelled=cancelled)
    if duration <= 0:
        return 1.0
    segment_count = max(config.segment_count, 1)
    return max(duration / segment_count, 1.0)


def _effective_duration_seconds(
    ffmpeg_binary: Path,
    source: Path,
    config: SourceProcessingConfig,
    *,
    cancelled: CancelledCallback | None = None,
) -> float:
    _raise_if_cancelled(cancelled)
    duration = _probe_duration_seconds(ffmpeg_binary, source)
    if not config.trim_enabled:
        return duration
    trimmed = duration - _mmss_to_seconds(config.trim_start) - _mmss_to_seconds(config.trim_end)
    return max(trimmed, 0.0)


def _probe_duration_seconds(ffmpeg_binary: Path, source: Path) -> float:
    completed = subprocess.run(
        [str(ffmpeg_binary), "-hide_banner", "-i", str(source)],
        capture_output=True,
        check=False,
    )
    content = f"{_decode_process_output(completed.stdout)}\n{_decode_process_output(completed.stderr)}"
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", content)
    if not match:
        summary = content.strip().splitlines()
        detail = summary[-1] if summary else ""
        if detail:
            raise FfmpegProcessError(f"Could not probe media duration: {source} ({detail})")
        raise FfmpegProcessError(f"Could not probe media duration: {source}")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return float(hours * 3600 + minutes * 60 + seconds)


def _run_ffmpeg_command(command: list[str], *, cancelled: CancelledCallback | None = None) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    while process.poll() is None:
        if cancelled is not None and cancelled():
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError(FFMPEG_CANCELLED_MESSAGE)
        time.sleep(0.2)

    stdout_bytes, stderr_bytes = process.communicate()
    stdout = _decode_process_output(stdout_bytes)
    stderr = _decode_process_output(stderr_bytes)
    if process.returncode != 0:
        summary = (stderr or stdout or "").strip()
        if summary:
            summary = summary.splitlines()[-1]
        raise FfmpegProcessError(summary or "FFmpeg process failed.")


def _decode_process_output(payload: bytes | None) -> str:
    if not payload:
        return ""
    for encoding in ("utf-8", "gb18030", "shift_jis"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _link_source(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(source, target)
        return
    except OSError:
        pass
    try:
        os.link(source, target)
        return
    except OSError:
        pass
    shutil.copy2(source, target)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path)


def _raise_if_cancelled(cancelled: CancelledCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError(FFMPEG_CANCELLED_MESSAGE)


def _mmss_to_seconds(value: str) -> float:
    normalized = value.strip()
    if not normalized:
        return 0.0
    parts = normalized.split(":")
    if len(parts) != 2:
        return 0.0
    try:
        minutes = int(parts[0])
        seconds = int(parts[1])
    except ValueError:
        return 0.0
    return float(minutes * 60 + seconds)


def _hhmmss_to_seconds(value: str) -> float:
    normalized = value.strip()
    if not normalized:
        return 0.0
    parts = normalized.split(":")
    if len(parts) != 3:
        return 0.0
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
    except ValueError:
        return 0.0
    return float(hours * 3600 + minutes * 60 + seconds)


def _format_hhmmss(seconds: float) -> str:
    if seconds <= 0:
        return "00:00:00"
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_ffmpeg_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _is_video_source(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES
