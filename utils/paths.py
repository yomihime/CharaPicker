from __future__ import annotations

import sys
from pathlib import Path

from core.models import ProjectPaths


def _resolve_app_root() -> Path:
    # In frozen/packaged runtime, __file__ may resolve into a temp extraction
    # directory; use the launch working directory as app root instead.
    if getattr(sys, "frozen", False):
        return Path.cwd().resolve()
    return Path(__file__).resolve().parents[1]


APP_ROOT = _resolve_app_root()
PROJECTS_ROOT = APP_ROOT / "projects"
LOGS_ROOT = APP_ROOT / "log"


def project_paths(project_id: str) -> ProjectPaths:
    root = PROJECTS_ROOT / project_id
    knowledge_base = root / "knowledge_base"
    return ProjectPaths(
        root=root,
        raw=root / "raw",
        materials=root / "materials",
        cache=root / "cache",
        knowledge_base=knowledge_base,
        output=root / "output",
        config=root / "config.json",
        facts=knowledge_base / "facts.json",
        targeted_insights=knowledge_base / "targeted_insights.json",
    )


def ensure_project_tree(project_id: str) -> ProjectPaths:
    paths = project_paths(project_id)
    for directory in (paths.raw, paths.materials, paths.cache, paths.knowledge_base, paths.output):
        directory.mkdir(parents=True, exist_ok=True)
    return paths
