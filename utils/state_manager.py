from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.models import ProjectConfig
from utils.atomic_io import (
    DataCorruptionError,
    read_validated_text,
    restore_backup_atomically,
    write_json_atomically,
    write_text_atomically_with_backup,
)
from utils.paths import PROJECTS_ROOT, ensure_project_tree, project_paths


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ProjectConfigScanResult:
    configs: list[ProjectConfig] = field(default_factory=list)
    issues: list[DataCorruptionError] = field(default_factory=list)


def save_project_config(config: ProjectConfig) -> Path:
    paths = ensure_project_tree(config.project_id)
    write_text_atomically_with_backup(
        paths.config,
        config.model_dump_json(indent=2) + "\n",
        _validate_project_config_text,
    )
    LOGGER.info("Project config saved; project_id=%s path=%s", config.project_id, paths.config)
    return paths.config


def create_project_config(config: ProjectConfig) -> Path:
    paths = ensure_project_tree(config.project_id)
    for data_file in (paths.facts, paths.targeted_insights):
        if not data_file.exists():
            write_json_atomically(data_file, [])
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
    config = _validate_project_config_text(
        read_validated_text(path, _validate_project_config_text)
    )
    LOGGER.debug("Project config loaded; project_id=%s path=%s", config.project_id, path)
    return config


def scan_project_configs(root: Path = PROJECTS_ROOT) -> ProjectConfigScanResult:
    result = ProjectConfigScanResult()
    if not root.exists():
        LOGGER.info("Projects root does not exist; path=%s", root)
        return result

    for config_path in sorted(root.glob("*/config.json")):
        try:
            result.configs.append(load_project_config(config_path))
        except DataCorruptionError as exc:
            result.issues.append(exc)
            LOGGER.warning(
                "Project config is corrupt; path=%s backup_available=%s backup_path=%s",
                exc.path,
                exc.backup_available,
                exc.backup_path,
            )
        except (json.JSONDecodeError, OSError, ValueError):
            LOGGER.warning("Project config skipped; path=%s", config_path, exc_info=True)
            continue
    result.configs.sort(key=lambda config: config.updated_at, reverse=True)
    LOGGER.info(
        "Project configs scanned; count=%s issues=%s",
        len(result.configs),
        len(result.issues),
    )
    return result


def list_project_configs(root: Path = PROJECTS_ROOT) -> list[ProjectConfig]:
    return scan_project_configs(root).configs


def restore_project_config_backup(path: Path) -> ProjectConfig:
    restore_backup_atomically(path, _validate_project_config_text)
    return load_project_config(path)


def _validate_project_config_text(text: str) -> ProjectConfig:
    return ProjectConfig.model_validate(json.loads(text))
