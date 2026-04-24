from __future__ import annotations

import json
from pathlib import Path

from core.models import ProjectConfig
from utils.paths import PROJECTS_ROOT, ensure_project_tree


def save_project_config(config: ProjectConfig) -> Path:
    paths = ensure_project_tree(config.project_id)
    paths.config.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return paths.config


def load_project_config(path: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_project_configs() -> list[ProjectConfig]:
    if not PROJECTS_ROOT.exists():
        return []

    configs: list[ProjectConfig] = []
    for config_path in sorted(PROJECTS_ROOT.glob("*/config.json")):
        try:
            configs.append(load_project_config(config_path))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return sorted(configs, key=lambda config: config.updated_at, reverse=True)
