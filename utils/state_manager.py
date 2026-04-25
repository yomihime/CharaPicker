from __future__ import annotations

import json
import logging
from pathlib import Path

from core.models import ProjectConfig
from utils.paths import PROJECTS_ROOT, ensure_project_tree


LOGGER = logging.getLogger(__name__)


def save_project_config(config: ProjectConfig) -> Path:
    paths = ensure_project_tree(config.project_id)
    paths.config.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Project config saved; project_id=%s path=%s", config.project_id, paths.config)
    return paths.config


def load_project_config(path: Path) -> ProjectConfig:
    config = ProjectConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    LOGGER.debug("Project config loaded; project_id=%s path=%s", config.project_id, path)
    return config


def list_project_configs() -> list[ProjectConfig]:
    if not PROJECTS_ROOT.exists():
        LOGGER.info("Projects root does not exist; path=%s", PROJECTS_ROOT)
        return []

    configs: list[ProjectConfig] = []
    for config_path in sorted(PROJECTS_ROOT.glob("*/config.json")):
        try:
            configs.append(load_project_config(config_path))
        except (json.JSONDecodeError, OSError, ValueError):
            LOGGER.warning("Project config skipped; path=%s", config_path, exc_info=True)
            continue
    sorted_configs = sorted(configs, key=lambda config: config.updated_at, reverse=True)
    LOGGER.info("Project configs listed; count=%s", len(sorted_configs))
    return sorted_configs
