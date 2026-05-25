from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils.global_store import get_global_value, set_global_value
from utils.paths import APP_ROOT

CONDA_ENV_NAME = "CharaPicker"
BIN_ROOT = APP_ROOT / "bin"
MODELS_ROOT = APP_ROOT / "models"
WHISPERCPP_ROOT = BIN_ROOT / "whisper.cpp"
WHISPER_MODEL_ROOT = MODELS_ROOT / "whisper"
WHISPER_RUNTIME_PATH_KEY = "tools/whispercpp/runtimePath"
WHISPER_MODEL_NAME_KEY = "tools/whispercpp/modelName"
LLAMACPP_CANDIDATES = (
    "llama-cli.exe",
    "llama-cli",
    "llama-server.exe",
    "llama-server",
    "llama.exe",
    "llama",
    "main.exe",
    "main",
)
LLAMACPP_CHECK_TIMEOUT_SECONDS = 6
WHISPERCPP_CANDIDATES = (
    "whisper-cli.exe",
    "whisper-cli",
    "main.exe",
    "main",
)
WHISPERCPP_CHECK_TIMEOUT_SECONDS = 6


@dataclass(frozen=True, slots=True)
class WhisperStatus:
    runtime_path: Path | None
    model_path: Path | None
    runtime_ready: bool
    model_ready: bool

    @property
    def ready(self) -> bool:
        return self.runtime_ready and self.model_ready


def conda_run_prefix() -> list[str]:
    return ["conda", "run", "-n", CONDA_ENV_NAME]


def find_llamacpp_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in LLAMACPP_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file():
            return candidate
    for file_name in LLAMACPP_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file():
                return candidate
    return None


def is_llamacpp_binary_usable(binary_path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(binary_path), "--help"],
            cwd=binary_path.parent,
            capture_output=True,
            timeout=LLAMACPP_CHECK_TIMEOUT_SECONDS,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def find_usable_llamacpp_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    for file_name in LLAMACPP_CANDIDATES:
        candidate = bin_root / file_name
        if candidate.is_file() and is_llamacpp_binary_usable(candidate):
            return candidate
    for file_name in LLAMACPP_CANDIDATES:
        for candidate in bin_root.rglob(file_name):
            if candidate.is_file() and is_llamacpp_binary_usable(candidate):
                return candidate
    return None


def has_llamacpp_binary(bin_root: Path = BIN_ROOT) -> bool:
    return find_usable_llamacpp_binary(bin_root) is not None


def custom_whisper_runtime_path() -> Path | None:
    stored_value = get_global_value(WHISPER_RUNTIME_PATH_KEY, "")
    if not isinstance(stored_value, str) or not stored_value.strip():
        return None
    return Path(stored_value.strip())


def set_custom_whisper_runtime_path(path: str | Path) -> None:
    set_global_value(WHISPER_RUNTIME_PATH_KEY, str(Path(path).expanduser()))


def clear_custom_whisper_runtime_path() -> None:
    set_global_value(WHISPER_RUNTIME_PATH_KEY, "")


def preferred_whisper_model_name() -> str:
    stored_value = get_global_value(WHISPER_MODEL_NAME_KEY, "")
    if not isinstance(stored_value, str):
        return ""
    return stored_value.strip()


def set_preferred_whisper_model_name(file_name: str) -> None:
    set_global_value(WHISPER_MODEL_NAME_KEY, Path(file_name).name)


def clear_preferred_whisper_model_name() -> None:
    set_global_value(WHISPER_MODEL_NAME_KEY, "")


def find_whisper_runtime_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    custom_path = custom_whisper_runtime_path()
    if bin_root == BIN_ROOT and custom_path is not None and custom_path.is_file():
        return custom_path

    search_roots = [WHISPERCPP_ROOT if bin_root == BIN_ROOT else bin_root / "whisper.cpp", bin_root]
    for search_root in search_roots:
        for file_name in WHISPERCPP_CANDIDATES:
            candidate = search_root / file_name
            if candidate.is_file():
                return candidate

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for file_name in WHISPERCPP_CANDIDATES:
            for candidate in search_root.rglob(file_name):
                if candidate.is_file():
                    return candidate
    return None


def is_whisper_runtime_usable(binary_path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(binary_path), "--help"],
            cwd=binary_path.parent,
            capture_output=True,
            timeout=WHISPERCPP_CHECK_TIMEOUT_SECONDS,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = f"{completed.stdout}\n{completed.stderr}".lower()
    return completed.returncode == 0 and ("whisper" in output or "usage" in output)


def find_usable_whisper_runtime_binary(bin_root: Path = BIN_ROOT) -> Path | None:
    custom_path = custom_whisper_runtime_path()
    if (
        bin_root == BIN_ROOT
        and custom_path is not None
        and custom_path.is_file()
        and is_whisper_runtime_usable(custom_path)
    ):
        return custom_path

    search_roots = [WHISPERCPP_ROOT if bin_root == BIN_ROOT else bin_root / "whisper.cpp", bin_root]
    for search_root in search_roots:
        for file_name in WHISPERCPP_CANDIDATES:
            candidate = search_root / file_name
            if candidate.is_file() and is_whisper_runtime_usable(candidate):
                return candidate

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for file_name in WHISPERCPP_CANDIDATES:
            for candidate in search_root.rglob(file_name):
                if candidate.is_file() and is_whisper_runtime_usable(candidate):
                    return candidate
    return None


def has_whisper_runtime(bin_root: Path = BIN_ROOT) -> bool:
    return find_usable_whisper_runtime_binary(bin_root) is not None


def list_whisper_model_files(model_root: Path = WHISPER_MODEL_ROOT) -> list[Path]:
    if not model_root.exists():
        return []
    model_files = [
        path
        for path in model_root.rglob("*.bin")
        if path.is_file() and path.name.lower().startswith("ggml-")
    ]
    return sorted(model_files, key=lambda path: path.name.lower())


def find_whisper_model_file(
    preferred_name: str = "ggml-tiny.bin",
    model_root: Path = WHISPER_MODEL_ROOT,
) -> Path | None:
    if model_root == WHISPER_MODEL_ROOT:
        preferred_name = preferred_whisper_model_name() or preferred_name
    preferred = model_root / preferred_name
    if preferred.is_file():
        return preferred
    model_files = list_whisper_model_files(model_root)
    return model_files[0] if model_files else None


def whisper_status(bin_root: Path = BIN_ROOT, model_root: Path = WHISPER_MODEL_ROOT) -> WhisperStatus:
    runtime_path = find_usable_whisper_runtime_binary(bin_root)
    model_path = find_whisper_model_file(model_root=model_root)
    return WhisperStatus(
        runtime_path=runtime_path,
        model_path=model_path,
        runtime_ready=runtime_path is not None,
        model_ready=model_path is not None,
    )
