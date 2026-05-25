from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import knowledge_base as kb
from core.models import EpisodeTranscript, TranscriptMetadata, TranscriptSegment, TranscriptSource
from utils.env_manager import whisper_status
from utils.ffmpeg_tool import FfmpegProcessError, extract_audio_to_wav
from utils.material_processing_events import SOURCE_PROCESSING_CANCELLED_MESSAGE
from utils.media_types import VIDEO_SUFFIXES
from utils.paths import ensure_project_tree


LOGGER = logging.getLogger(__name__)
AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"})
WHISPER_BACKEND_ID = "whisper.cpp"
ProgressCallback = Callable[[str, int], None]
CancelCallback = Callable[[], bool]
FALLBACK_MESSAGES = {
    "transcription.error.noSource": "No material file is available for transcription.",
    "transcription.error.sourceMissing": "Material file does not exist: {path}",
    "transcription.error.unsupportedSource": "This material format is not supported for transcription yet: {path}",
    "transcription.error.whisperRuntimeMissing": "No usable whisper.cpp runtime was found.",
    "transcription.error.whisperModelMissing": "No usable Whisper model was found.",
    "transcription.error.ffmpegRequired": "Could not extract audio: {error}",
    "transcription.error.whisperFailed": "whisper.cpp transcription failed: {error}",
    "transcription.error.outputParseFailed": "Could not parse whisper.cpp output: {error}",
    "transcription.error.noOutput": "whisper.cpp did not produce a usable transcript.",
    "transcription.error.cancelled": "Audio transcription was cancelled.",
}


@dataclass(frozen=True, slots=True)
class TranscriptionOptions:
    language: str = "auto"
    force_rebuild: bool = False


class AudioTranscriptionError(RuntimeError):
    pass


class AudioTranscriptionCancelled(AudioTranscriptionError):
    pass


def transcribe_episode_audio(
    project_id: str,
    season_id: str,
    episode_id: str,
    material_paths: Path | str | Sequence[Path | str],
    *,
    options: TranscriptionOptions | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> EpisodeTranscript:
    options = options or TranscriptionOptions()
    sources = _normalize_material_paths(material_paths)
    if not sources:
        raise AudioTranscriptionError(_message("transcription.error.noSource"))
    for source in sources:
        if not source.is_file():
            raise AudioTranscriptionError(
                _message("transcription.error.sourceMissing", path=str(source))
            )

    status = whisper_status()
    if not status.runtime_ready or status.runtime_path is None:
        raise AudioTranscriptionError(_message("transcription.error.whisperRuntimeMissing"))
    if not status.model_ready or status.model_path is None:
        raise AudioTranscriptionError(_message("transcription.error.whisperModelMissing"))

    _emit(progress, "fingerprint", 5)
    fingerprints = [_file_fingerprint(source) for source in sources]
    source_fingerprint = _combined_fingerprint(fingerprints)
    runtime_version, runtime_package = _runtime_identity(status.runtime_path)
    model_fingerprint = _file_identity(status.model_path)
    language = _normalize_language(options.language)
    cache_key = _cache_key(
        sources=sources,
        source_fingerprint=source_fingerprint,
        runtime_path=status.runtime_path,
        runtime_version=runtime_version,
        runtime_package=runtime_package,
        model_path=status.model_path,
        model_fingerprint=model_fingerprint,
        language=language,
    )

    cached = _load_cached_transcript(project_id, season_id, episode_id)
    if cached is not None and not options.force_rebuild and cached.transcription.cache_key == cache_key:
        LOGGER.info(
            "Episode transcript cache hit; project_id=%s season_id=%s episode_id=%s segments=%s chars=%s",
            project_id,
            season_id,
            episode_id,
            len(cached.segments),
            len(cached.plain_text),
        )
        _emit(progress, "cached", 100)
        return cached

    paths = ensure_project_tree(project_id)
    paths.cache.mkdir(parents=True, exist_ok=True)
    LOGGER.info(
        "Episode audio transcription started; project_id=%s season_id=%s episode_id=%s sources=%s model=%s",
        project_id,
        season_id,
        episode_id,
        len(sources),
        status.model_path.name,
    )
    segments: list[TranscriptSegment] = []
    material_time_ranges: list[dict[str, Any]] = []
    offset_seconds = 0.0

    with tempfile.TemporaryDirectory(prefix="transcription-", dir=paths.cache) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        total_sources = len(sources)
        for index, source in enumerate(sources, start=1):
            _check_cancel(cancelled)
            _emit(progress, "prepare", 10 + int((index - 1) * 20 / total_sources))
            audio_path = _prepare_audio_input(source, temp_dir, index, cancelled)
            output_prefix = temp_dir / f"whisper_{index:03d}"
            _emit(progress, "run", 30 + int((index - 1) * 55 / total_sources))
            _run_whisper_cli(
                runtime_path=status.runtime_path,
                model_path=status.model_path,
                audio_path=audio_path,
                output_prefix=output_prefix,
                language=language,
                cancelled=cancelled,
            )
            try:
                source_segments, source_plain_text = _parse_whisper_outputs(
                    output_prefix.with_suffix(".json"),
                    output_prefix.with_suffix(".txt"),
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise AudioTranscriptionError(
                    _message("transcription.error.outputParseFailed", error=str(exc))
                ) from exc
            if not source_segments and not source_plain_text.strip():
                raise AudioTranscriptionError(_message("transcription.error.noOutput"))
            if not source_segments and source_plain_text.strip():
                source_segments = [
                    TranscriptSegment(
                        start_seconds=0.0,
                        end_seconds=0.0,
                        text=source_plain_text.strip(),
                    )
                ]
            range_start = offset_seconds
            segments.extend(_offset_segments(source_segments, offset_seconds))
            offset_seconds += _segment_duration_guess(source_segments)
            material_time_ranges.append(
                {
                    "material_path": str(source),
                    "start_seconds": range_start,
                    "end_seconds": offset_seconds,
                }
            )

    plain_text = "\n".join(segment.text.strip() for segment in segments if segment.text.strip())
    transcript = EpisodeTranscript(
        schema_version=1,
        source=TranscriptSource(
            material_path=str(sources[0]),
            material_paths=[str(source) for source in sources],
            material_time_ranges=material_time_ranges,
            source_fingerprint=source_fingerprint,
            season_id=season_id,
            episode_id=episode_id,
        ),
        transcription=TranscriptMetadata(
            backend=WHISPER_BACKEND_ID,
            runtime_version=runtime_version,
            runtime_package=runtime_package,
            runtime_path=str(status.runtime_path),
            model_file=status.model_path.name,
            model_path=str(status.model_path),
            language=language,
            cache_key=cache_key,
        ),
        segments=segments,
        plain_text=plain_text,
    )
    kb.save_episode_transcript(project_id, transcript)
    _emit(progress, "done", 100)
    LOGGER.info(
        "Episode transcript saved; project_id=%s season_id=%s episode_id=%s segments=%s chars=%s",
        project_id,
        season_id,
        episode_id,
        len(transcript.segments),
        len(transcript.plain_text),
    )
    return transcript


def _emit(progress: ProgressCallback | None, step: str, value: int) -> None:
    if progress is not None:
        progress(step, value)


def _message(key: str, **kwargs: object) -> str:
    try:
        from utils.i18n import t as translate

        return translate(key, **kwargs)
    except Exception:  # noqa: BLE001
        template = FALLBACK_MESSAGES.get(key, key)
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template


def transcript_segments_for_range(
    transcript: EpisodeTranscript,
    start_seconds: float,
    end_seconds: float,
    *,
    max_chars: int = 4000,
) -> str:
    selected: list[str] = []
    for segment in transcript.segments:
        if segment.end_seconds and segment.end_seconds < start_seconds:
            continue
        if segment.start_seconds > end_seconds:
            continue
        text = segment.text.strip()
        if text:
            selected.append(
                f"[{_format_seconds(segment.start_seconds)}-{_format_seconds(segment.end_seconds)}] {text}"
            )
    output = "\n".join(selected)
    if len(output) <= max_chars:
        return output
    return output[: max(max_chars - 3, 0)].rstrip() + "..."


def transcript_segments_for_material(
    transcript: EpisodeTranscript,
    material_path: Path | str,
    *,
    max_chars: int = 4000,
) -> str:
    target = _path_identity(material_path)
    for item in transcript.source.material_time_ranges:
        if not isinstance(item, dict):
            continue
        item_path = item.get("material_path")
        if not isinstance(item_path, str) or _path_identity(item_path) != target:
            continue
        start_seconds = _coerce_float(item.get("start_seconds"))
        end_seconds = _coerce_float(item.get("end_seconds"))
        return transcript_segments_for_range(
            transcript,
            start_seconds,
            end_seconds,
            max_chars=max_chars,
        )

    material_paths = {_path_identity(path) for path in transcript.source.material_paths}
    if target in material_paths:
        return _clamp_text(transcript.plain_text, max_chars)
    return ""


def _normalize_material_paths(material_paths: Path | str | Sequence[Path | str]) -> list[Path]:
    if isinstance(material_paths, str | Path):
        return [Path(material_paths).expanduser().resolve()]
    return [Path(path).expanduser().resolve() for path in material_paths]


def _load_cached_transcript(
    project_id: str,
    season_id: str,
    episode_id: str,
) -> EpisodeTranscript | None:
    path = kb.episode_transcript_path(project_id, season_id, episode_id)
    if not path.exists():
        return None
    try:
        return kb.load_episode_transcript(project_id, season_id, episode_id)
    except (OSError, ValueError, json.JSONDecodeError):
        LOGGER.warning(
            "Episode transcript cache ignored because it could not be read; "
            "project_id=%s season_id=%s episode_id=%s",
            project_id,
            season_id,
            episode_id,
            exc_info=True,
        )
        return None


def _prepare_audio_input(
    source: Path,
    temp_dir: Path,
    index: int,
    cancelled: CancelCallback | None,
) -> Path:
    suffix = source.suffix.lower()
    if suffix == ".wav":
        return source
    if suffix not in VIDEO_SUFFIXES and suffix not in AUDIO_SUFFIXES:
        raise AudioTranscriptionError(
            _message("transcription.error.unsupportedSource", path=str(source))
        )
    target = temp_dir / f"audio_{index:03d}.wav"
    try:
        return extract_audio_to_wav(source, target, cancelled=cancelled)
    except RuntimeError as exc:
        if str(exc) == SOURCE_PROCESSING_CANCELLED_MESSAGE:
            raise AudioTranscriptionCancelled(_message("transcription.error.cancelled")) from exc
        raise
    except FfmpegProcessError as exc:
        raise AudioTranscriptionError(
            _message("transcription.error.ffmpegRequired", error=str(exc))
        ) from exc


def _run_whisper_cli(
    *,
    runtime_path: Path,
    model_path: Path,
    audio_path: Path,
    output_prefix: Path,
    language: str,
    cancelled: CancelCallback | None,
) -> None:
    command = [
        str(runtime_path),
        "-m",
        str(model_path),
        "-f",
        str(audio_path),
        "-oj",
        "-otxt",
        "-of",
        str(output_prefix),
    ]
    if language != "auto":
        command.extend(["-l", language])

    process = subprocess.Popen(
        command,
        cwd=runtime_path.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        while True:
            try:
                stdout_bytes, stderr_bytes = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                _check_cancel(cancelled)
    except AudioTranscriptionCancelled:
        LOGGER.info("whisper.cpp transcription cancellation detected; terminating process pid=%s", process.pid)
        _terminate_process(process)
        process.communicate()
        raise

    if process.returncode != 0:
        raise AudioTranscriptionError(
            _message(
                "transcription.error.whisperFailed",
                error=_compact_process_error(stderr_bytes, stdout_bytes),
            )
        )


def _parse_whisper_outputs(json_path: Path, text_path: Path) -> tuple[list[TranscriptSegment], str]:
    segments: list[TranscriptSegment] = []
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        segments = _segments_from_payload(payload)
    plain_text = ""
    if text_path.exists():
        plain_text = text_path.read_text(encoding="utf-8").strip()
    if not plain_text and segments:
        plain_text = "\n".join(segment.text for segment in segments if segment.text.strip())
    return (segments, plain_text)


def _segments_from_payload(payload: Any) -> list[TranscriptSegment]:
    if not isinstance(payload, dict):
        return []
    raw_segments = payload.get("transcription")
    if not isinstance(raw_segments, list):
        raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return []

    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start_seconds, end_seconds = _segment_timestamps(item)
        segments.append(
            TranscriptSegment(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=text,
            )
        )
    return segments


def _segment_timestamps(item: dict[str, Any]) -> tuple[float, float]:
    timestamps = item.get("timestamps")
    if isinstance(timestamps, dict):
        start = _parse_timestamp(timestamps.get("from"))
        end = _parse_timestamp(timestamps.get("to"))
        if start is not None or end is not None:
            return (float(start or 0.0), float(end or start or 0.0))

    offsets = item.get("offsets")
    if isinstance(offsets, dict):
        start = _parse_offset_seconds(offsets.get("from"))
        end = _parse_offset_seconds(offsets.get("to"))
        if start is not None or end is not None:
            return (float(start or 0.0), float(end or start or 0.0))

    start = _parse_offset_seconds(item.get("start"))
    end = _parse_offset_seconds(item.get("end"))
    if start is None:
        start = _parse_offset_seconds(item.get("t0"))
    if end is None:
        end = _parse_offset_seconds(item.get("t1"))
    return (float(start or 0.0), float(end or start or 0.0))


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return _parse_offset_seconds(value)
    text = value.strip().replace(",", ".")
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        return float(text)
    except ValueError:
        return None


def _parse_offset_seconds(value: Any) -> float | None:
    if not isinstance(value, int | float):
        return None
    numeric = float(value)
    if numeric > 1000:
        return numeric / 1000.0
    return numeric


def _offset_segments(segments: list[TranscriptSegment], offset_seconds: float) -> list[TranscriptSegment]:
    if offset_seconds <= 0:
        return segments
    return [
        segment.model_copy(
            update={
                "start_seconds": segment.start_seconds + offset_seconds,
                "end_seconds": segment.end_seconds + offset_seconds if segment.end_seconds else 0.0,
            }
        )
        for segment in segments
    ]


def _segment_duration_guess(segments: list[TranscriptSegment]) -> float:
    if not segments:
        return 0.0
    return max(max(segment.start_seconds, segment.end_seconds) for segment in segments)


def _file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _file_identity(path: Path) -> str:
    stat = path.stat()
    return f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"


def _combined_fingerprint(fingerprints: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for fingerprint in fingerprints:
        digest.update(fingerprint.encode("utf-8"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _cache_key(
    *,
    sources: Sequence[Path],
    source_fingerprint: str,
    runtime_path: Path,
    runtime_version: str,
    runtime_package: str,
    model_path: Path,
    model_fingerprint: str,
    language: str,
) -> str:
    payload = {
        "schema_version": 1,
        "backend": WHISPER_BACKEND_ID,
        "sources": [str(source) for source in sources],
        "source_fingerprint": source_fingerprint,
        "runtime_path": str(runtime_path),
        "runtime_version": runtime_version,
        "runtime_package": runtime_package,
        "model_path": str(model_path),
        "model_fingerprint": model_fingerprint,
        "language": language,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _runtime_identity(runtime_path: Path) -> tuple[str, str]:
    parts = runtime_path.resolve().parts
    try:
        marker_index = next(
            index for index, part in enumerate(parts) if part.lower() == "whisper.cpp"
        )
    except StopIteration:
        return ("custom", "custom")

    version = parts[marker_index + 1] if len(parts) > marker_index + 1 else "unknown"
    package = parts[marker_index + 2] if len(parts) > marker_index + 2 else "unknown"
    return (version, package)


def _normalize_language(language: str) -> str:
    normalized = language.strip().lower()
    return normalized or "auto"


def _format_seconds(value: float) -> str:
    whole = max(int(value), 0)
    return f"{whole // 60:02d}:{whole % 60:02d}"


def _path_identity(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve()).lower()


def _coerce_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 3, 0)].rstrip() + "..."


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise AudioTranscriptionCancelled(_message("transcription.error.cancelled"))


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


def _compact_process_error(stderr_bytes: bytes | None, stdout_bytes: bytes | None) -> str:
    for payload in (stderr_bytes, stdout_bytes):
        text = _decode_process_output(payload)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1][:240]
    return "unknown error"


def _decode_process_output(payload: bytes | None) -> str:
    if not payload:
        return ""
    for encoding in ("utf-8", "gb18030", "shift_jis"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")
