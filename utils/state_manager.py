from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from core.models import ProjectConfig
from utils.paths import PROJECTS_ROOT, ensure_project_tree, project_paths


LOGGER = logging.getLogger(__name__)
EMPTY_JSON_LIST = "[]\n"


def save_project_config(config: ProjectConfig) -> Path:
    paths = ensure_project_tree(config.project_id)
    paths.config.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Project config saved; project_id=%s path=%s", config.project_id, paths.config)
    return paths.config


def create_project_config(config: ProjectConfig) -> Path:
    paths = ensure_project_tree(config.project_id)
    for data_file in (paths.facts, paths.targeted_insights):
        if not data_file.exists():
            data_file.write_text(EMPTY_JSON_LIST, encoding="utf-8")
    return save_project_config(config)


def delete_project_config(project_id: str) -> None:
    project_root = project_paths(project_id).root.resolve()
    projects_root = PROJECTS_ROOT.resolve()
    if project_root == projects_root or projects_root not in project_root.parents:
        raise ValueError(f"Unsafe project path: {project_root}")
    if project_root.exists():
        shutil.rmtree(project_root)
        LOGGER.info("Project deleted; project_id=%s path=%s", project_id, project_root)


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
