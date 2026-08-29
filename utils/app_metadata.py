"""Shared runtime application metadata."""


def format_version_tag(version: str, release_stage: str) -> str:
    """Return the public version label for a release stage."""
    stage = release_stage.strip()
    if not stage or stage.lower() == "release":
        return version
    return f"{version}-{stage}"


APP_NAME = "CharaPicker"
APP_ORGANIZATION_NAME = APP_NAME
APP_VERSION = "1.0.0"
APP_RELEASE_STAGE = "release"
APP_VERSION_TAG = format_version_tag(APP_VERSION, APP_RELEASE_STAGE)

HTTP_USER_AGENT = f"{APP_NAME}/{APP_VERSION_TAG}"
