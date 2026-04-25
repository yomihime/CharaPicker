from __future__ import annotations

import logging

from pydantic import BaseModel

from utils.global_store import get_global_value, set_global_value


LOGGER = logging.getLogger(__name__)
PROMPT_SETTINGS_KEY = "prompts/custom"


class PromptOverride(BaseModel):
    system: str = ""
    user_template: str = ""


def prompt_overrides() -> dict[str, PromptOverride]:
    raw_value = get_global_value(PROMPT_SETTINGS_KEY, {})
    if not isinstance(raw_value, dict):
        return {}

    overrides: dict[str, PromptOverride] = {}
    for purpose, raw_prompt in raw_value.items():
        if not isinstance(raw_prompt, dict):
            continue
        override = PromptOverride.model_validate(raw_prompt)
        if override.system.strip() or override.user_template.strip():
            overrides[str(purpose)] = override
    return overrides


def prompt_override(purpose: str) -> PromptOverride:
    return prompt_overrides().get(purpose, PromptOverride())


def set_prompt_override(purpose: str, override: PromptOverride) -> None:
    overrides = prompt_overrides()
    if override.system.strip() or override.user_template.strip():
        overrides[purpose] = override
    else:
        overrides.pop(purpose, None)

    set_global_value(
        PROMPT_SETTINGS_KEY,
        {key: value.model_dump() for key, value in overrides.items()},
    )
    LOGGER.info("Prompt override saved; purpose=%s has_override=%s", purpose, purpose in overrides)


def clear_prompt_override(purpose: str) -> None:
    overrides = prompt_overrides()
    overrides.pop(purpose, None)
    set_global_value(
        PROMPT_SETTINGS_KEY,
        {key: value.model_dump() for key, value in overrides.items()},
    )
    LOGGER.info("Prompt override cleared; purpose=%s", purpose)
