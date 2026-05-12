from __future__ import annotations

from pathlib import Path

from utils.paths import APP_ROOT


MODELS_ROOT = APP_ROOT / "models"
LOCAL_MODEL_SUFFIXES = {".bin", ".gguf", ".model", ".onnx", ".pt", ".pth", ".safetensors"}


def list_local_model_candidates() -> list[Path]:
    if not MODELS_ROOT.exists():
        return []

    candidates: list[Path] = []
    for path in sorted(MODELS_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if path.name.startswith("."):
            continue
        if path.is_file() and is_model_file(path):
            candidates.append(path.relative_to(APP_ROOT))
            continue
        if path.is_dir() and directory_contains_model(path):
            candidates.append(path.relative_to(APP_ROOT))
    return candidates


def directory_contains_model(path: Path) -> bool:
    return any(candidate.is_file() and is_model_file(candidate) for candidate in path.rglob("*"))


def is_model_file(path: Path) -> bool:
    return path.suffix.lower() in LOCAL_MODEL_SUFFIXES
