from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import quote

from utils.global_store import get_global_value, set_global_value


LOGGER = logging.getLogger(__name__)

PROXY_SETTINGS_KEY = "network/proxy"
ProxyScheme = Literal["http", "https", "socks5"]
SUPPORTED_PROXY_SCHEMES: tuple[ProxyScheme, ...] = ("http", "https", "socks5")
DEFAULT_PROXY_SCHEME: ProxyScheme = "http"
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 7890
DEFAULT_CUSTOM_TEST_URL = "https://example.com/"


@dataclass(slots=True)
class ProxySettings:
    enabled: bool = False
    scheme: ProxyScheme = DEFAULT_PROXY_SCHEME
    remote_dns: bool = True
    host: str = DEFAULT_PROXY_HOST
    port: int = DEFAULT_PROXY_PORT
    username: str = ""
    password: str = ""
    custom_test_url: str = DEFAULT_CUSTOM_TEST_URL

    @property
    def is_configured(self) -> bool:
        return bool(self.host.strip() and 1 <= int(self.port) <= 65535)

    @property
    def effective_scheme(self) -> str:
        if self.scheme == "socks5" and self.remote_dns:
            return "socks5h"
        return self.scheme

    def proxy_url(self, *, include_credentials: bool = True) -> str:
        if not self.is_configured:
            return ""
        host = self.host.strip()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        credentials = ""
        if include_credentials and self.username:
            credentials = quote(self.username, safe="")
            if self.password:
                credentials += f":{quote(self.password, safe='')}"
            credentials += "@"
        return f"{self.effective_scheme}://{credentials}{host}:{self.port}"

    def sanitized_proxy_url(self) -> str:
        if not self.is_configured:
            return ""
        host = self.host.strip()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        credentials = "***:***@" if self.username or self.password else ""
        return f"{self.effective_scheme}://{credentials}{host}:{self.port}"

    def to_store(self) -> dict[str, object]:
        return asdict(self)


def load_proxy_settings() -> ProxySettings:
    raw_value = get_global_value(PROXY_SETTINGS_KEY, {})
    if not isinstance(raw_value, dict):
        LOGGER.warning("Proxy settings ignored because stored value is not a mapping")
        return ProxySettings()
    return normalize_proxy_settings(raw_value)


def save_proxy_settings(settings: ProxySettings) -> ProxySettings:
    normalized = normalize_proxy_settings(settings.to_store())
    set_global_value(PROXY_SETTINGS_KEY, normalized.to_store())
    LOGGER.info(
        "Proxy settings saved; enabled=%s scheme=%s remote_dns=%s has_host=%s has_auth=%s",
        normalized.enabled,
        normalized.scheme,
        normalized.remote_dns,
        bool(normalized.host),
        bool(normalized.username or normalized.password),
    )
    return normalized


def normalize_proxy_settings(value: dict[str, object]) -> ProxySettings:
    scheme = _normalize_scheme(value.get("scheme"))
    return ProxySettings(
        enabled=_coerce_bool(value.get("enabled")),
        scheme=scheme,
        remote_dns=_coerce_bool(value.get("remote_dns"), default=True),
        host=_normalize_host(value.get("host")),
        port=_coerce_port(value.get("port")),
        username=str(value.get("username", "") or "").strip(),
        password=str(value.get("password", "") or ""),
        custom_test_url=_normalize_custom_test_url(value.get("custom_test_url")),
    )


def _normalize_scheme(value: object) -> ProxyScheme:
    scheme = str(value or "").strip().lower()
    if scheme in SUPPORTED_PROXY_SCHEMES:
        return scheme  # type: ignore[return-value]
    return DEFAULT_PROXY_SCHEME


def _normalize_host(value: object) -> str:
    host = str(value or "").strip()
    return host or DEFAULT_PROXY_HOST


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_port(value: object) -> int:
    if value is None:
        return DEFAULT_PROXY_PORT
    if isinstance(value, str) and not value.strip():
        return DEFAULT_PROXY_PORT
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 0
    return port if 1 <= port <= 65535 else 0


def _normalize_custom_test_url(value: object) -> str:
    url = str(value or "").strip()
    return url or DEFAULT_CUSTOM_TEST_URL
