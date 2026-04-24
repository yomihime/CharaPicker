from __future__ import annotations

CONDA_ENV_NAME = "CharaPicker"


def conda_run_prefix() -> list[str]:
    return ["conda", "run", "-n", CONDA_ENV_NAME]
