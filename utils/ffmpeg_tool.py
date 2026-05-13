from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.models import SourceProcessingConfig, SourceProcessingPreset, SourceSegmentMode
from utils.env_manager import BIN_ROOT
from utils.ffmpeg_detection import (
    detect_cpu_name as _detect_cpu_name,
    detect_video_device_names as _detect_video_device_names,
    pick_device as _pick_device,
)
from utils.paths import ensure_project_tree
import logging

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
FFMPEG_EVENT_PREFIX = "__ffmpeg_event__:"
ProgressCallback = Callable[[int, int, str], None]
CancelledCallback = Callable[[], bool]
FfmpegProgressCallback = Callable[[int, float], None]

LOGGER = logging.getLogger(__name__)


class FfmpegProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class EncoderOption:
    encoder: str
    label: str
    is_cpu: bool
    device_name: str


@dataclass(frozen=True)
class DeviceOption:
    device_id: str
    label: str
    is_cpu: bool
    encoders: dict[str, str]


@dataclass(frozen=True)
class _DeviceCapability:
    device_id: str
    label: str
    is_cpu: bool
    encoders: dict[str, str]


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


def probe_video_duration_seconds(source: Path, bin_root: Path = BIN_ROOT) -> float:
    ffmpeg_binary = find_usable_ffmpeg_binary(bin_root)
    if ffmpeg_binary is None:
        raise FfmpegProcessError("FFmpeg is required to probe video duration.")
    return _probe_duration_seconds(ffmpeg_binary, source)


def list_available_device_options(bin_root: Path = BIN_ROOT) -> list[DeviceOption]:
    ffmpeg_binary = find_usable_ffmpeg_binary(bin_root)
    if ffmpeg_binary is None:
        return []
    supported_encoders = _read_supported_video_encoders(ffmpeg_binary)
    if not supported_encoders:
        return []
    capabilities = _collect_device_capabilities(supported_encoders)
    return [
        DeviceOption(
            device_id=item.device_id,
            label=item.label,
            is_cpu=item.is_cpu,
            encoders=dict(item.encoders),
        )
        for item in capabilities
        if item.encoders
    ]


def list_available_encoder_options(bin_root: Path = BIN_ROOT) -> list[EncoderOption]:
    ffmpeg_binary = find_usable_ffmpeg_binary(bin_root)
    if ffmpeg_binary is None:
        return []
    supported_encoders = _read_supported_video_encoders(ffmpeg_binary)
    if not supported_encoders:
        return []

    gpu_names = _detect_video_device_names()
    cpu_name = _detect_cpu_name()
    nvidia_device = _pick_device(gpu_names, ["nvidia"])
    amd_device = _pick_device(gpu_names, ["amd", "radeon"])
    intel_device = _pick_device(gpu_names, ["intel"])

    candidates: list[tuple[str, str, str, bool, str]] = [
        ("av1_nvenc", "NVIDIA NVENC AV1", "nvidia", False, nvidia_device),
        ("h264_nvenc", "NVIDIA NVENC H.264", "nvidia", False, nvidia_device),
        ("hevc_nvenc", "NVIDIA NVENC HEVC", "nvidia", False, nvidia_device),
        ("av1_amf", "AMD AMF AV1", "amd", False, amd_device),
        ("h264_amf", "AMD AMF H.264", "amd", False, amd_device),
        ("hevc_amf", "AMD AMF HEVC", "amd", False, amd_device),
        ("av1_qsv", "QuickSync AV1", "intel", False, intel_device),
        ("h264_qsv", "QuickSync H.264", "intel", False, intel_device),
        ("hevc_qsv", "QuickSync HEVC", "intel", False, intel_device),
        ("libsvtav1", "SVT-AV1", "cpu", True, cpu_name),
        ("libaom-av1", "AOM AV1", "cpu", True, cpu_name),
        ("libx264", "x264", "cpu", True, cpu_name),
        ("libx265", "x265", "cpu", True, cpu_name),
    ]

    options: list[EncoderOption] = []
    for encoder, title, vendor, is_cpu, device in candidates:
        if encoder not in supported_encoders:
            continue
        if vendor == "nvidia" and not nvidia_device:
            continue
        if vendor == "amd" and not amd_device:
            continue
        if vendor == "intel" and not intel_device:
            continue
        label = f"{title} ({device})" if device else title
        options.append(EncoderOption(encoder=encoder, label=label, is_cpu=is_cpu, device_name=device))
    return options


def resolve_video_encoder_name(codec_format: str, preferred_device: str = "", *, bin_root: Path = BIN_ROOT) -> str:
    ffmpeg_binary = find_usable_ffmpeg_binary(bin_root)
    if ffmpeg_binary is None:
        raise FfmpegProcessError("FFmpeg is unavailable.")
    supported_encoders = _read_supported_video_encoders(ffmpeg_binary)
    capabilities = _collect_device_capabilities(supported_encoders)
    codec_key = _normalize_codec_key(codec_format)
    if not codec_key:
        raise FfmpegProcessError(f"Unsupported target codec: {codec_format}")

    preferred = preferred_device.strip().lower()
    if preferred:
        if preferred in supported_encoders:
            if not _is_encoder_compatible(codec_key, preferred):
                raise FfmpegProcessError(
                    f"Selected encoder '{preferred_device}' does not support target codec '{codec_format}'."
                )
            return preferred

        capability = _find_device_capability(capabilities, preferred_device)
        if capability is None:
            raise FfmpegProcessError(f"Selected device is unavailable: {preferred_device}")
        matched = capability.encoders.get(codec_key, "")
        if not matched:
            raise FfmpegProcessError(
                f"Selected device '{capability.label}' does not support target codec '{codec_format}'."
            )
        return matched

    for capability in capabilities:
        matched = capability.encoders.get(codec_key, "")
        if matched:
            return matched
    raise FfmpegProcessError(f"No available encoder can encode target codec '{codec_format}'.")


def is_device_compatible_for_codec(codec_format: str, selected_device: str, *, bin_root: Path = BIN_ROOT) -> bool:
    ffmpeg_binary = find_usable_ffmpeg_binary(bin_root)
    if ffmpeg_binary is None:
        return False
    supported_encoders = _read_supported_video_encoders(ffmpeg_binary)
    codec_key = _normalize_codec_key(codec_format)
    if not codec_key:
        return False
    preferred = selected_device.strip().lower()
    if preferred in supported_encoders:
        return _is_encoder_compatible(codec_key, preferred)
    capability = _find_device_capability(_collect_device_capabilities(supported_encoders), selected_device)
    if capability is None:
        return False
    return codec_key in capability.encoders


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
    processing_items: list[tuple[Path, Path, bool]] = []
    for source in raw_sources:
        try:
            relative_path = source.resolve().relative_to(raw_root.resolve())
        except ValueError:
            continue
        processing_items.append((source, relative_path, _is_video_source(source)))

    total = len(processing_items)
    if progress is not None:
        progress(0, total, "")

    video_items = [(source, relative_path) for source, relative_path, is_video in processing_items if is_video]
    total_video_count = len(video_items)
    video_total_frames: dict[str, int] = {}
    overall_total_frames = 0

    if total_video_count > 0:
        if progress is not None:
            progress(
                0,
                0,
                _encode_ffmpeg_event(
                    {
                        "stage": "preparing",
                        "message_key": "project.processing.dialog.preparing.probe",
                    }
                ),
            )
        for probe_index, (video_source, relative_path) in enumerate(video_items, start=1):
            _raise_if_cancelled(cancelled)
            if progress is not None:
                progress(
                    0,
                    0,
                    _encode_ffmpeg_event(
                        {
                            "stage": "preparing",
                            "message_key": "project.processing.dialog.preparing.file",
                            "name": relative_path.as_posix(),
                            "current": probe_index,
                            "total": total_video_count,
                        }
                    ),
                )
            estimated_frames = _estimate_total_frames(ffmpeg_binary, video_source, processing_config, cancelled=cancelled)
            video_total_frames[str(video_source.resolve())] = estimated_frames
            overall_total_frames += estimated_frames

    processed_count = 0
    overall_done_base = 0
    rollback_entries: list[tuple[Path, Path | None]] = []
    try:
        for index, (source, relative_path, is_video) in enumerate(processing_items, start=1):
            _raise_if_cancelled(cancelled)
            relative_name = relative_path.as_posix()
            target = materials_root / relative_path
            backup_target = _backup_target(target)
            rollback_entries.append((target, backup_target))
            _remove_path(target)

            if is_video:
                total_frames = video_total_frames.get(str(source.resolve()), 1)
                _process_video_with_ffmpeg(
                    ffmpeg_binary,
                    source,
                    target,
                    processing_config,
                    cancelled=cancelled,
                    progress_callback=(
                        _build_processing_progress_callback(
                            progress,
                            relative_name,
                            total_frames,
                            overall_done_base,
                            overall_total_frames,
                            total_video_count > 1,
                        )
                        if progress is not None
                        else None
                    ),
                )
                overall_done_base += max(total_frames, 1)
            else:
                _link_source(source, target)

            processed_count += 1
            if progress is not None and not is_video:
                progress(index, total, relative_name)
    except Exception:
        LOGGER.info("source processing interrupted; rolling back material changes")
        for target, backup in reversed(rollback_entries):
            _restore_target_from_backup(target, backup)
        raise

    for _, backup in rollback_entries:
        _remove_path(backup)
    return processed_count


def _process_video_with_ffmpeg(
    ffmpeg_binary: Path,
    source: Path,
    target: Path,
    config: SourceProcessingConfig,
    *,
    cancelled: CancelledCallback | None = None,
    progress_callback: FfmpegProgressCallback | None = None,
) -> None:
    target.mkdir(parents=True, exist_ok=True)

    if config.preset == SourceProcessingPreset.TRANSCODE_ONLY:
        output_path = target / "transcoded.mp4"
        command = _build_transcode_command(ffmpeg_binary, source, output_path, config)
        _run_ffmpeg_command(command, cancelled=cancelled, on_progress=progress_callback)
        if progress_callback is not None:
            progress_callback(10**12, 0.0)
        return

    segment_seconds = _segment_seconds(ffmpeg_binary, source, config, cancelled=cancelled)
    if segment_seconds <= 0:
        segment_seconds = 1.0

    if config.preset == SourceProcessingPreset.SEGMENT_ONLY:
        output_suffix = source.suffix.lower() if source.suffix else ".mp4"
        output_pattern = target / f"segment_%03d{output_suffix}"
        command = _build_segment_only_command(ffmpeg_binary, source, output_pattern, segment_seconds, config)
        _run_ffmpeg_command(command, cancelled=cancelled, on_progress=progress_callback)
        if progress_callback is not None:
            progress_callback(10**12, 0.0)
        return

    if config.preset == SourceProcessingPreset.SEGMENT_TRANSCODE:
        output_pattern = target / "segment_%03d.mp4"
        command = _build_segment_transcode_command(ffmpeg_binary, source, output_pattern, segment_seconds, config)
        _run_ffmpeg_command(command, cancelled=cancelled, on_progress=progress_callback)
        if progress_callback is not None:
            progress_callback(10**12, 0.0)
        return

    raise FfmpegProcessError(f"Unsupported preset: {config.preset}")


def _build_transcode_command(ffmpeg_binary: Path, source: Path, output_path: Path, config: SourceProcessingConfig) -> list[str]:
    command = _base_ffmpeg_command(ffmpeg_binary)
    command.extend(_hwaccel_args(config))
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
    command.extend(_hwaccel_args(config))
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
    return [str(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:2", "-y"]


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
    encoder_name = resolve_video_encoder_name(config.codec, config.encoder)
    args = ["-c:v", encoder_name, "-c:a", "aac", "-movflags", "+faststart"]
    args.extend(_video_filter_args(config.resolution, encoder_name))
    return args


def _hwaccel_args(config: SourceProcessingConfig) -> list[str]:
    encoder_name = resolve_video_encoder_name(config.codec, config.encoder)
    if encoder_name.endswith("_nvenc"):
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    return []


def _video_filter_args(resolution: str, encoder_name: str) -> list[str]:
    height = _resolution_height(resolution)
    if not height:
        return []
    if encoder_name.endswith("_nvenc"):
        # CUDA decode path outputs CUDA frames, so scaling must stay on GPU.
        return ["-vf", f"scale_cuda=-2:{height}:format=nv12"]
    return ["-vf", f"scale=-2:{height}"]


def _resolution_height(resolution: str) -> str:
    normalized = resolution.strip().lower()
    if normalized == "540p":
        return "540"
    if normalized == "720p":
        return "720"
    if normalized == "1080p":
        return "1080"
    return ""


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
    duration = _probe_duration_seconds(ffmpeg_binary, source, cancelled=cancelled)
    if not config.trim_enabled:
        return duration
    trimmed = duration - _mmss_to_seconds(config.trim_start) - _mmss_to_seconds(config.trim_end)
    return max(trimmed, 0.0)


def _estimate_total_frames(
    ffmpeg_binary: Path,
    source: Path,
    config: SourceProcessingConfig,
    *,
    cancelled: CancelledCallback | None = None,
) -> int:
    _raise_if_cancelled(cancelled)
    duration_seconds = _effective_duration_seconds(ffmpeg_binary, source, config, cancelled=cancelled)
    if duration_seconds <= 0:
        return 1
    fps = _probe_frame_rate(ffmpeg_binary, source, cancelled=cancelled)
    if fps <= 0:
        fps = 24.0
    return max(int(round(duration_seconds * fps)), 1)


def _probe_frame_rate(
    ffmpeg_binary: Path,
    source: Path,
    *,
    cancelled: CancelledCallback | None = None,
) -> float:
    content = _probe_media_output(ffmpeg_binary, source, cancelled=cancelled)
    for pattern in (
        r"Video:.*?(\d+(?:\.\d+)?)\s*fps",
        r"Video:.*?(\d+(?:\.\d+)?)\s*tbr",
    ):
        match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        try:
            fps = float(match.group(1))
        except ValueError:
            continue
        if fps > 0:
            return fps
    return 0.0


def _probe_duration_seconds(
    ffmpeg_binary: Path,
    source: Path,
    *,
    cancelled: CancelledCallback | None = None,
) -> float:
    content = _probe_media_output(ffmpeg_binary, source, cancelled=cancelled)
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


def _probe_media_output(
    ffmpeg_binary: Path,
    source: Path,
    *,
    cancelled: CancelledCallback | None = None,
) -> str:
    process = subprocess.Popen(
        [str(ffmpeg_binary), "-hide_banner", "-i", str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        while process.poll() is None:
            _raise_if_cancelled(cancelled)
            time.sleep(0.1)
    except RuntimeError:
        LOGGER.info("ffmpeg probe cancellation detected; terminating process pid=%s", process.pid)
        _terminate_process(process)
        if process.stdout is not None:
            process.stdout.read()
        process.wait()
        raise
    stdout_bytes, stderr_bytes = process.communicate()
    return f"{_decode_process_output(stdout_bytes)}\n{_decode_process_output(stderr_bytes)}"


def _run_ffmpeg_command(
    command: list[str],
    *,
    cancelled: CancelledCallback | None = None,
    on_progress: FfmpegProgressCallback | None = None,
) -> None:
    LOGGER.info("Running FFmpeg command: %s", subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr_lines: list[str] = []
    progress_snapshot: dict[str, str] = {}
    progress_state = {"frame": 0, "fps": 0.0}
    progress_lock = threading.Lock()

    def _read_stderr() -> None:
        if process.stderr is None:
            return
        while True:
            raw_line = process.stderr.readline()
            if not raw_line:
                break
            line = _decode_process_output(raw_line).strip()
            if not line:
                continue
            stderr_lines.append(line)
            if _update_ffmpeg_progress_snapshot(progress_snapshot, line):
                frame = _parse_frame_value(progress_snapshot.get("frame", ""))
                fps = _parse_fps_value(progress_snapshot.get("fps", ""))
                with progress_lock:
                    progress_state["frame"] = frame
                    progress_state["fps"] = fps

    stderr_reader = threading.Thread(target=_read_stderr, daemon=True)
    stderr_reader.start()
    last_emitted_frame = -1
    while process.poll() is None:
        if cancelled is not None and cancelled():
            LOGGER.info("ffmpeg cancellation detected; terminating process pid=%s", process.pid)
            _terminate_process(process)
            if process.stdout is not None:
                process.stdout.read()
            process.wait()
            stderr_reader.join(timeout=2)
            raise RuntimeError(FFMPEG_CANCELLED_MESSAGE)
        if on_progress is not None:
            with progress_lock:
                current_frame = int(progress_state["frame"])
                current_fps = float(progress_state["fps"])
            if current_frame != last_emitted_frame:
                last_emitted_frame = current_frame
                on_progress(current_frame, current_fps)
        time.sleep(0.2)

    stdout_bytes = b""
    if process.stdout is not None:
        stdout_bytes = process.stdout.read()
    process.wait()
    stderr_reader.join(timeout=2)
    stdout = _decode_process_output(stdout_bytes)
    if on_progress is not None:
        final_frame = _parse_frame_value(progress_snapshot.get("frame", ""))
        final_fps = _parse_fps_value(progress_snapshot.get("fps", ""))
        on_progress(final_frame, final_fps)
    if process.returncode != 0:
        summary = _extract_ffmpeg_error_summary(stderr_lines, stdout)
        raise FfmpegProcessError(summary or "FFmpeg process failed.")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            process.terminate()
            process.wait(timeout=2)
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


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


def _remove_path(path: Path | None) -> None:
    if path is None:
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path)


def _backup_target(target: Path) -> Path | None:
    if not target.exists() and not target.is_symlink():
        return None
    backup = target.parent / f"{target.name}.rollback.{int(time.time() * 1000)}"
    _remove_path(backup)
    target.rename(backup)
    return backup


def _restore_target_from_backup(target: Path, backup: Path | None) -> None:
    _remove_path(target)
    if backup is None:
        return
    if backup.exists() or backup.is_symlink():
        backup.rename(target)


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


def _build_processing_progress_callback(
    progress: ProgressCallback,
    relative_name: str,
    total_frames: int,
    overall_done_base: int,
    overall_total_frames: int,
    overall_enabled: bool,
) -> FfmpegProgressCallback:
    effective_total = max(total_frames, 1)

    def _emit(frame_done: int, fps: float) -> None:
        clamped_done = max(0, min(frame_done, effective_total))
        file_percent = (clamped_done / effective_total) * 100.0
        overall_total = max(overall_total_frames, effective_total)
        overall_done = max(0, min(overall_done_base + clamped_done, overall_total))
        overall_percent = (overall_done / overall_total) * 100.0
        payload = {
            "stage": "processing",
            "name": relative_name,
            "file_done": clamped_done,
            "file_total": effective_total,
            "file_percent": round(file_percent, 2),
            "fps": round(max(fps, 0.0), 2),
            "overall_enabled": overall_enabled,
            "overall_done": overall_done,
            "overall_total": overall_total,
            "overall_percent": round(overall_percent, 2),
        }
        progress(
            overall_done if overall_enabled else clamped_done,
            overall_total if overall_enabled else effective_total,
            _encode_ffmpeg_event(payload),
        )

    return _emit


def _update_ffmpeg_progress_snapshot(snapshot: dict[str, str], line: str) -> str:
    if "=" not in line:
        return ""
    key, value = line.split("=", 1)
    normalized_key = key.strip().lower()
    normalized_value = value.strip()
    if not normalized_key:
        return ""
    snapshot[normalized_key] = normalized_value
    if normalized_key == "progress":
        return _format_ffmpeg_progress_snapshot(snapshot)
    return ""


def _format_ffmpeg_progress_snapshot(snapshot: dict[str, str]) -> str:
    frame = snapshot.get("frame", "?")
    fps = snapshot.get("fps", "?")
    speed = snapshot.get("speed", "?")
    time_text = _format_ffmpeg_out_time(snapshot)
    return f"frame={frame} fps={fps} speed={speed} time={time_text}"


def _parse_frame_value(value: str) -> int:
    try:
        return max(int(value.strip()), 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _parse_fps_value(value: str) -> float:
    try:
        parsed = float(value.strip())
        return parsed if parsed >= 0 else 0.0
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _format_ffmpeg_out_time(snapshot: dict[str, str]) -> str:
    out_time = snapshot.get("out_time", "").strip()
    if out_time:
        return out_time
    microseconds = snapshot.get("out_time_ms", "").strip()
    if not microseconds:
        return "?"
    try:
        total_seconds = max(int(microseconds) / 1_000_000.0, 0.0)
    except ValueError:
        return "?"
    whole = int(total_seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    seconds = whole % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _extract_ffmpeg_error_summary(stderr_lines: list[str], stdout: str) -> str:
    for line in reversed(stderr_lines):
        if _looks_like_ffmpeg_progress_line(line):
            continue
        return line.strip()
    summary = (stdout or "").strip()
    if not summary:
        return ""
    lines = [item.strip() for item in summary.splitlines() if item.strip()]
    return lines[-1] if lines else ""


def _looks_like_ffmpeg_progress_line(line: str) -> bool:
    return bool(re.match(r"^[a-z0-9_]+=", line.strip().lower()))


def _encode_ffmpeg_event(payload: dict[str, object]) -> str:
    return f"{FFMPEG_EVENT_PREFIX}{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"


def _read_supported_video_encoders(ffmpeg_binary: Path) -> set[str]:
    try:
        completed = subprocess.run(
            [str(ffmpeg_binary), "-hide_banner", "-encoders"],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    content = f"{_decode_process_output(completed.stdout)}\n{_decode_process_output(completed.stderr)}"
    encoders: set[str] = set()
    for line in content.splitlines():
        match = re.match(r"^\s*([A-Z\.]{6})\s+([A-Za-z0-9_\-]+)\s+", line)
        if not match:
            continue
        flags = match.group(1)
        encoder = match.group(2).strip().lower()
        if "V" not in flags:
            continue
        encoders.add(encoder)
    return encoders


def _pick_first_supported_encoder(preferred: tuple[str, ...], *, bin_root: Path = BIN_ROOT) -> str:
    ffmpeg_binary = find_usable_ffmpeg_binary(bin_root)
    if ffmpeg_binary is None:
        return preferred[-1]
    supported = _read_supported_video_encoders(ffmpeg_binary)
    for encoder in preferred:
        if encoder in supported:
            return encoder
    return preferred[-1]


def _is_encoder_compatible(codec_format: str, encoder_name: str) -> bool:
    normalized_codec = codec_format.strip().lower()
    normalized_encoder = encoder_name.strip().lower()
    if normalized_codec in {"h.264", "h264"}:
        return "h264" in normalized_encoder or normalized_encoder == "libx264"
    if normalized_codec in {"h.265", "h265", "hevc"}:
        return "hevc" in normalized_encoder or normalized_encoder == "libx265"
    if normalized_codec in {"av1"}:
        return "av1" in normalized_encoder or normalized_encoder in {"libsvtav1", "libaom-av1"}
    return False


def _normalize_codec_key(codec_format: str) -> str:
    normalized = codec_format.strip().lower()
    if normalized in {"h.264", "h264"}:
        return "h264"
    if normalized in {"h.265", "h265", "hevc"}:
        return "hevc"
    if normalized in {"av1"}:
        return "av1"
    return ""


def _collect_device_capabilities(supported_encoders: set[str]) -> list[_DeviceCapability]:
    gpu_names = _detect_video_device_names()
    cpu_name = _detect_cpu_name()
    nvidia_device = _pick_device(gpu_names, ["nvidia"])
    amd_device = _pick_device(gpu_names, ["amd", "radeon"])
    intel_device = _pick_device(gpu_names, ["intel"])

    capabilities: list[_DeviceCapability] = []
    if nvidia_device:
        mappings = _codec_encoder_mapping(
            supported_encoders,
            h264="h264_nvenc",
            hevc="hevc_nvenc",
            av1="av1_nvenc",
        )
        if mappings:
            capabilities.append(
                _DeviceCapability(
                    device_id="nvidia",
                    label=nvidia_device,
                    is_cpu=False,
                    encoders=mappings,
                )
            )

    if amd_device:
        mappings = _codec_encoder_mapping(
            supported_encoders,
            h264="h264_amf",
            hevc="hevc_amf",
            av1="av1_amf",
        )
        if mappings:
            capabilities.append(
                _DeviceCapability(
                    device_id="amd",
                    label=amd_device,
                    is_cpu=False,
                    encoders=mappings,
                )
            )

    if intel_device:
        mappings = _codec_encoder_mapping(
            supported_encoders,
            h264="h264_qsv",
            hevc="hevc_qsv",
            av1="av1_qsv",
        )
        if mappings:
            capabilities.append(
                _DeviceCapability(
                    device_id="intel",
                    label=intel_device,
                    is_cpu=False,
                    encoders=mappings,
                )
            )

    cpu_mappings = _codec_encoder_mapping(
        supported_encoders,
        h264="libx264",
        hevc="libx265",
        av1="libsvtav1",
    )
    if "av1" not in cpu_mappings and "libaom-av1" in supported_encoders:
        cpu_mappings["av1"] = "libaom-av1"
    if cpu_mappings:
        capabilities.append(
            _DeviceCapability(
                device_id="cpu",
                label=cpu_name,
                is_cpu=True,
                encoders=cpu_mappings,
            )
        )
    return capabilities


def _codec_encoder_mapping(supported: set[str], **codec_encoder: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for codec_key, encoder_name in codec_encoder.items():
        if encoder_name in supported:
            mapping[codec_key] = encoder_name
    return mapping


def _find_device_capability(capabilities: list[_DeviceCapability], selected_device: str) -> _DeviceCapability | None:
    candidate = selected_device.strip().lower()
    if not candidate:
        return None
    for capability in capabilities:
        if capability.device_id.lower() == candidate:
            return capability
    for capability in capabilities:
        if capability.label.lower() == candidate:
            return capability
    return None
