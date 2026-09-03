"""Guards ported from UpBoard's connector: sensitive models, secret fields, read-safe methods."""

from __future__ import annotations

from typing import Any

# Models holding secrets or allowing code execution. Refused unless the
# caller explicitly opts in (--include-sensitive / allow_sensitive).
SENSITIVE_MODELS: frozenset[str] = frozenset(
    {
        "ir.config_parameter",
        "ir.property",
        "ir.cron",
        "ir.actions.server",
        "ir.rule",
        "ir.model.access",
        "base.module.update",
        "base.module.upgrade",
        "base.language.install",
        "res.users.apikeys",
        "auth.totp.device",
        "ir.mail_server",
        "fetchmail.server",
    }
)

# Field-name substrings whose VALUE is masked in output (case-insensitive).
SENSITIVE_FIELD_PATTERNS: tuple[str, ...] = (
    "password",
    "passwd",
    "smtp_pass",
    "api_key",
    "apikey",
    "secret",
    "private_key",
    "totp_secret",
)

# Methods that never change data: callable without allow_writes or --yes.
READ_SAFE_METHODS: frozenset[str] = frozenset(
    {
        "search",
        "search_read",
        "search_count",
        "read",
        "read_group",
        "fields_get",
        "name_search",
        "name_get",
        "default_get",
        "get_metadata",
        "check_access_rights",
        "get_views",
        "web_search_read",
        "web_read_group",
        "has_group",
        "get_external_id",
    }
)

REDACTED = "[redacted]"


def is_sensitive_model(model: str) -> bool:
    return model in SENSITIVE_MODELS


def is_sensitive_field(name: str) -> bool:
    lowered = name.lower()
    return any(p in lowered for p in SENSITIVE_FIELD_PATTERNS)


def redact(data: Any) -> Any:
    """Replace values of secret-named keys, recursively, in lists and dicts."""
    if isinstance(data, list):
        return [redact(i) for i in data]
    if isinstance(data, dict):
        return {k: (REDACTED if is_sensitive_field(str(k)) else redact(v)) for k, v in data.items()}
    return data


def is_read_safe_method(method: str) -> bool:
    return method in READ_SAFE_METHODS
