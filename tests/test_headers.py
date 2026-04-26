from __future__ import annotations

from autocli.headers import is_session_sensitive_header, strip_session_sensitive_headers


def test_session_sensitive_header_filter_covers_shared_security_patterns() -> None:
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer secret",
        "Cookie": "session=secret",
        "Set-Cookie": "session=secret; HttpOnly",
        "X-CSRF-Token": "csrf-123",
        "X-Session-Id": "session-123",
        "X-Auth-Mode": "token",
        "Sec-Fetch-Site": "same-origin",
        "X-Trace-Id": "trace-123",
    }

    assert strip_session_sensitive_headers(headers) == {
        "Accept": "application/json",
        "X-Trace-Id": "trace-123",
    }
    assert is_session_sensitive_header("Authorization") is True
    assert is_session_sensitive_header("Set-Cookie") is True
    assert is_session_sensitive_header("X-Session-Id") is True
    assert is_session_sensitive_header("X-Trace-Id") is False
