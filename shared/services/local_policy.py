"""Central local-first policy helpers for runtime services."""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

_TRUTHY = {"1", "true", "yes", "on"}
_LOCAL_MODEL_PREFIXES = ("ollama/",)


def env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().casefold()
    if not raw:
        return bool(default)
    return raw in _TRUTHY


def local_first_enabled() -> bool:
    return env_flag("D2C_LOCAL_FIRST", default=True)


def remote_llm_allowed() -> bool:
    if not local_first_enabled():
        return True
    return env_flag("D2C_ALLOW_REMOTE_LLM", default=False)


def remote_telemetry_allowed() -> bool:
    if not local_first_enabled():
        return True
    return env_flag("D2C_ALLOW_REMOTE_TELEMETRY", default=False)


def plugin_network_allowed() -> bool:
    if not local_first_enabled():
        return True
    return env_flag("D2C_ALLOW_PLUGIN_NETWORK", default=False)


def is_local_host(host: str) -> bool:
    value = str(host or "").strip().strip("[]").casefold()
    if not value:
        return False
    if value in {"localhost", "0.0.0.0", "::1"}:
        return True
    try:
        return bool(ipaddress.ip_address(value).is_loopback)
    except ValueError:
        return False


def is_local_http_endpoint(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    scheme = str(parsed.scheme or "").strip().casefold()
    if scheme in {"http+unix", "unix", "file"}:
        return True
    if scheme not in {"http", "https"}:
        return False
    return is_local_host(str(parsed.hostname or ""))


def is_local_litellm_target(model_ref: str, api_base: str) -> bool:
    if remote_llm_allowed():
        return True
    model = str(model_ref or "").strip().casefold()
    if model.startswith(_LOCAL_MODEL_PREFIXES):
        return True
    return is_local_http_endpoint(api_base)


def langsmith_tracing_enabled() -> bool:
    requested = env_flag("LANGSMITH_TRACING", default=False) or env_flag(
        "LANGCHAIN_TRACING_V2",
        default=False,
    )
    if not requested:
        return False
    if remote_telemetry_allowed():
        return True
    endpoint = (
        str(os.environ.get("LANGSMITH_ENDPOINT", "") or "").strip()
        or str(os.environ.get("LANGCHAIN_ENDPOINT", "") or "").strip()
    )
    return is_local_http_endpoint(endpoint)
