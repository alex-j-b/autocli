"""Shared HTTP header filtering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SESSION_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "csrf-token",
        "set-cookie",
        "set-cookie2",
        "x-csrf-token",
        "x-requested-with",
        "x-xsrf-token",
        "xsrf-token",
    }
)
SESSION_SENSITIVE_HEADER_PREFIXES = ("sec-",)
SESSION_SENSITIVE_HEADER_SUBSTRINGS = ("auth", "csrf", "session", "token")


def strip_session_sensitive_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """Remove headers that should only be supplied at runtime."""

    return {name: value for name, value in headers.items() if not is_session_sensitive_header(name)}


def is_session_sensitive_header(header_name: str) -> bool:
    """Return whether a header should never be persisted in generated artifacts."""

    normalized = header_name.lower()
    if normalized in SESSION_SENSITIVE_HEADER_NAMES:
        return True
    if normalized.startswith(SESSION_SENSITIVE_HEADER_PREFIXES):
        return True
    return any(token in normalized for token in SESSION_SENSITIVE_HEADER_SUBSTRINGS)
