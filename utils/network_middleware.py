from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from utils.proxy_preferences import ProxySettings, load_proxy_settings


NETWORK_LOCK = threading.RLock()
PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
NO_PROXY_ENV_KEYS = ("NO_PROXY", "no_proxy")
AUTHORIZATION_RE = re.compile(r"(Authorization:\s*Bearer\s+|Bearer\s+)([A-Za-z0-9._~+/=-]+)")
OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
URL_WITH_CREDENTIALS_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9+.-]*://)([^/\s:@]+(?::[^/\s@]*)?@)"
)
SENSITIVE_URL_QUERY_KEYS = {
    "access_key",
    "access_key_id",
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}


class NetworkMiddlewareError(RuntimeError):
    pass


class ProxyConfigurationError(NetworkMiddlewareError):
    pass


class NetworkRequestError(NetworkMiddlewareError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectivityTarget:
    target_id: str
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class ConnectivityResult:
    target_id: str
    label: str
    url: str
    ok: bool
    status_code: int | None = None
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "label": self.label,
            "url": self.url,
            "ok": self.ok,
            "status_code": self.status_code,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


FIXED_CONNECTIVITY_TARGETS: tuple[ConnectivityTarget, ...] = (
    ConnectivityTarget("google", "Google", "https://www.google.com/generate_204"),
    ConnectivityTarget("cloudflare", "Cloudflare", "https://www.cloudflare.com/cdn-cgi/trace"),
    ConnectivityTarget("baidu", "Baidu", "https://www.baidu.com/"),
)


def request_proxies(settings: ProxySettings | None = None) -> dict[str, str] | None:
    settings = settings or load_proxy_settings()
    proxy_url = active_proxy_url(settings)
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def active_proxy_url(settings: ProxySettings | None = None) -> str:
    settings = settings or load_proxy_settings()
    if not settings.enabled:
        return ""
    if not settings.is_configured:
        raise ProxyConfigurationError("Proxy is enabled but host or port is not configured.")
    return settings.proxy_url()


def sanitized_active_proxy_url(settings: ProxySettings | None = None) -> str:
    settings = settings or load_proxy_settings()
    return settings.sanitized_proxy_url() if settings.enabled else ""


@contextmanager
def open_response(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | str | None = None,
    json_payload: Any = None,
    timeout: int | float = 30,
    stream: bool = False,
    allow_redirects: bool = True,
) -> Iterator[requests.Response]:
    settings = load_proxy_settings()
    with NETWORK_LOCK:
        session = requests.Session()
        session.trust_env = not settings.enabled
        try:
            response = session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                json=json_payload,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
                proxies=request_proxies(settings),
            )
            try:
                yield response
            finally:
                response.close()
        except requests.RequestException as exc:
            raise NetworkRequestError(redact_sensitive_text(str(exc))) from exc
        finally:
            session.close()


def read_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int | float = 30,
) -> Any:
    with open_response("GET", url, headers=headers, timeout=timeout) as response:
        if response.status_code >= 400:
            raise NetworkRequestError(
                redact_sensitive_text(f"HTTP {response.status_code}: {response.text[:500]}")
            )
        return response.json()


def test_connectivity(
    target: ConnectivityTarget,
    *,
    timeout: int | float = 5,
) -> ConnectivityResult:
    started = time.monotonic()
    try:
        status_code = _probe_status_code(target.url, timeout=timeout)
        ok = 200 <= status_code < 500
        error = "" if ok else f"HTTP {status_code}"
    except Exception as exc:  # noqa: BLE001
        status_code = None
        ok = False
        error = redact_sensitive_text(str(exc))
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ConnectivityResult(
        target_id=target.target_id,
        label=target.label,
        url=target.url,
        ok=ok,
        status_code=status_code,
        error=error,
        elapsed_ms=elapsed_ms,
    )


def custom_connectivity_target(url: str) -> ConnectivityTarget:
    normalized = url.strip()
    if not normalized.lower().startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return ConnectivityTarget("custom", "Custom", normalized)


def run_with_proxy_environment(callback: Callable[[], Any]) -> Any:
    settings = load_proxy_settings()
    with NETWORK_LOCK:
        if not settings.enabled:
            return callback()

        proxy_url = active_proxy_url(settings)
        original_values = {
            key: os.environ.get(key) for key in (*PROXY_ENV_KEYS, *NO_PROXY_ENV_KEYS)
        }
        try:
            for key in PROXY_ENV_KEYS:
                os.environ[key] = proxy_url
            for key in NO_PROXY_ENV_KEYS:
                os.environ.pop(key, None)
            return callback()
        finally:
            for key, value in original_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    if not text:
        return text

    text = URL_WITH_CREDENTIALS_RE.sub(r"\1***:***@", text)
    text = AUTHORIZATION_RE.sub(r"\1***", text)
    text = OPENAI_KEY_RE.sub("sk-***", text)

    settings = load_proxy_settings()
    full_proxy = settings.proxy_url(include_credentials=True)
    sanitized_proxy = settings.sanitized_proxy_url()
    if full_proxy and sanitized_proxy:
        text = text.replace(full_proxy, sanitized_proxy)
    for secret in (settings.password, settings.username):
        if secret and len(secret) >= 3:
            text = text.replace(secret, "***")
    return text


def sanitize_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return redact_sensitive_text(url)

    netloc = parsed.netloc
    host = parsed.hostname or ""
    if parsed.username or parsed.password:
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"***:***@{host}"
        if parsed.port:
            netloc += f":{parsed.port}"
    query = _sanitize_url_query(parsed.query)
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def _sanitize_url_query(query: str) -> str:
    if not query:
        return ""
    sanitized_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.strip().lower().replace("-", "_")
        if normalized_key in SENSITIVE_URL_QUERY_KEYS or normalized_key.endswith("_token"):
            sanitized_pairs.append((key, "***"))
        else:
            sanitized_pairs.append((key, value))
    return urlencode(sanitized_pairs, safe="*")


def _probe_status_code(url: str, *, timeout: int | float) -> int:
    with open_response("HEAD", url, timeout=timeout, allow_redirects=True) as response:
        if response.status_code not in {405, 501}:
            return response.status_code
    with open_response("GET", url, timeout=timeout, allow_redirects=True) as response:
        return response.status_code
