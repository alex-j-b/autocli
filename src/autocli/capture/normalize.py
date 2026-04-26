"""Capture normalization helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import msgpack

DEFAULT_PORTS = {
    'http': 80,
    'https': 443,
}


def normalize_exchanges(raw_exchanges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a sequence of raw exchanges."""

    return [normalize_exchange(exchange) for exchange in raw_exchanges]


def normalize_exchange(raw_exchange: dict[str, Any]) -> dict[str, Any]:
    """Normalize one raw capture exchange into the compiler's plain-data record."""

    source = dict(raw_exchange['source'])
    request = dict(raw_exchange['request'])
    response = dict(raw_exchange['response'])

    request_headers = normalize_headers(request.get('headers', {}))
    response_headers = normalize_headers(response.get('headers', {}))

    request_url = str(request.get('url', ''))
    if source.get('format') == 'flow':
        request_url = repair_flow_request_url(request, request_headers)

    parsed_url = urlsplit(request_url)
    scheme = (parsed_url.scheme or str(request.get('scheme') or '') or 'https').lower()
    host = (parsed_url.hostname or str(request.get('host') or '') or host_from_headers(request_headers) or '').lower()
    if not host:
        raise ValueError('request host is required after normalization')

    port = parsed_url.port or coerce_int(request.get('port')) or DEFAULT_PORTS.get(scheme)
    path = parsed_url.path or '/'
    query = normalize_query(parse_qsl(parsed_url.query, keep_blank_values=True))
    if not query and request.get('query'):
        query = normalize_query(request['query'])

    request_media_type = extract_media_type(first_value(request_headers.get('content-type')))
    response_media_type = extract_media_type(first_value(response_headers.get('content-type')))

    return {
        'source': {
            'format': str(source['format']),
            'source_path': str(source['source_path']),
            'capture_id': str(source['capture_id']),
            'captured_at': normalize_timestamp(source.get('captured_at')),
        },
        'request': {
            'method': str(request['method']).upper(),
            'url': urlunsplit((scheme, build_netloc(host, port, scheme), path, parsed_url.query, '')),
            'scheme': scheme,
            'host': host,
            'port': port,
            'path': path,
            'query': query,
            'headers': request_headers,
            'body': coerce_body_bytes(request.get('body'), request_media_type),
            'media_type': request_media_type,
        },
        'response': {
            'status': int(response['status']),
            'headers': response_headers,
            'body': coerce_body_bytes(response.get('body'), response_media_type),
            'media_type': response_media_type,
        },
        'compiler': {
            'skip_reason': None,
        },
    }


def normalize_headers(raw_headers: Any) -> dict[str, str | list[str]]:
    """Normalize headers into lowercase keys while preserving repeated values."""

    if raw_headers is None:
        return {}

    items: list[tuple[str, str]] = []
    if isinstance(raw_headers, dict):
        for key, value in raw_headers.items():
            if isinstance(value, list):
                items.extend((str(key), str(item)) for item in value)
            else:
                items.append((str(key), str(value)))
    else:
        for item in raw_headers:
            if isinstance(item, tuple) and len(item) == 2:
                items.append((str(item[0]), str(item[1])))
            elif isinstance(item, dict):
                items.append((str(item['name']), str(item.get('value', ''))))
            else:
                raise TypeError(f'unsupported header item {item!r}')

    normalized: dict[str, str | list[str]] = {}
    for key, value in items:
        normalized_key = key.lower()
        current = normalized.get(normalized_key)
        if current is None:
            normalized[normalized_key] = value
        elif isinstance(current, list):
            current.append(value)
        else:
            normalized[normalized_key] = [current, value]
    return normalized


def normalize_query(raw_query: Any) -> dict[str, str | list[str]]:
    """Normalize query parameters while preserving repeated keys."""

    if raw_query is None:
        return {}

    items: list[tuple[str, str]] = []
    if isinstance(raw_query, dict):
        for key, value in raw_query.items():
            if isinstance(value, list):
                items.extend((str(key), str(item)) for item in value)
            else:
                items.append((str(key), str(value)))
    else:
        for item in raw_query:
            if isinstance(item, tuple) and len(item) == 2:
                items.append((str(item[0]), str(item[1])))
            elif isinstance(item, dict):
                items.append((str(item['name']), str(item.get('value', ''))))
            else:
                raise TypeError(f'unsupported query item {item!r}')

    normalized: dict[str, str | list[str]] = {}
    for key, value in items:
        current = normalized.get(key)
        if current is None:
            normalized[key] = value
        elif isinstance(current, list):
            current.append(value)
        else:
            normalized[key] = [current, value]
    return normalized


def extract_media_type(content_type: str | None) -> str | None:
    """Extract the media type token from a ``Content-Type`` header."""

    if not content_type:
        return None
    return content_type.split(';', 1)[0].strip().lower() or None


def extract_charset(content_type: str | None) -> str | None:
    """Extract a charset parameter from ``Content-Type``."""

    if not content_type:
        return None
    parts = [part.strip() for part in content_type.split(';')]
    for part in parts[1:]:
        if part.lower().startswith('charset='):
            return part.split('=', 1)[1].strip() or None
    return None


def decode_body_bytes(body: bytes | bytearray | memoryview | None, content_type: str | None) -> Any:
    """Decode body bytes using the content-type hint when possible."""

    if not body:
        return None

    body_bytes = bytes(body)
    media_type = extract_media_type(content_type)

    if media_type in {'application/json', 'application/ld+json'} or (media_type and media_type.endswith('+json')):
        return json.loads(body_bytes)
    if media_type in {'application/msgpack', 'application/x-msgpack'}:
        return msgpack.unpackb(body_bytes, raw=False)
    if media_type == 'application/x-www-form-urlencoded':
        return normalize_query(
            parse_qsl(body_bytes.decode(extract_charset(content_type) or 'utf-8'), keep_blank_values=True)
        )
    if media_type and media_type.startswith('text/'):
        return body_bytes.decode(extract_charset(content_type) or 'utf-8')
    return body_bytes


def repair_flow_request_url(request: dict[str, Any], headers: dict[str, str | list[str]]) -> str:
    """Repair malformed mitmproxy flow URLs using host-related fallbacks."""

    raw_url = str(request.get('url', ''))
    parsed = urlsplit(raw_url)
    if parsed.scheme and parsed.hostname:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))

    host_hint = str(request.get('host_header') or '') or host_from_headers(headers) or str(request.get('host') or '')
    if not host_hint:
        raise ValueError('unable to repair flow URL without host information')

    host, host_port = split_host_port(host_hint)
    scheme = (
        parsed.scheme
        or str(request.get('scheme') or '')
        or infer_scheme_from_port(coerce_int(request.get('port')) or host_port)
    ).lower()
    port = coerce_int(request.get('port')) or host_port or DEFAULT_PORTS.get(scheme)

    raw_path = str(request.get('path') or parsed.path or '/')
    if not raw_path.startswith('/'):
        raw_path = f'/{raw_path}'
    path_split = urlsplit(f'{scheme}://{host}{raw_path}')
    path = path_split.path or '/'
    query = path_split.query or parsed.query

    return urlunsplit((scheme, build_netloc(host, port, scheme), path, query, ''))


def host_from_headers(headers: dict[str, str | list[str]]) -> str | None:
    """Extract a host hint from normalized headers."""

    host_header = first_value(headers.get('host'))
    if not host_header:
        return None
    host, _ = split_host_port(host_header)
    return host


def split_host_port(value: str) -> tuple[str, int | None]:
    """Split a host header into host and optional port."""

    parsed = urlsplit(f'//{value}')
    return (parsed.hostname or value.split(':', 1)[0], parsed.port)


def build_netloc(host: str, port: int | None, scheme: str) -> str:
    """Render a canonical network location."""

    if port is None or port == DEFAULT_PORTS.get(scheme):
        return host
    return f'{host}:{port}'


def infer_scheme_from_port(port: int | None) -> str:
    """Infer a scheme from a port number."""

    if port == 80:
        return 'http'
    return 'https'


def first_value(value: str | list[str] | None) -> str | None:
    """Return the first string value from a normalized multi-value field."""

    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def coerce_body_bytes(body: Any, media_type: str | None) -> bytes:
    """Coerce an incoming body value to bytes."""

    if body is None:
        return b''
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, memoryview):
        return bytes(body)
    if isinstance(body, str):
        return body.encode(extract_charset(media_type) or 'utf-8')
    raise TypeError(f'unsupported body value {body!r}')


def normalize_timestamp(value: Any) -> str | None:
    """Normalize capture timestamps to ISO-8601 strings when possible."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).isoformat().replace('+00:00', 'Z')
    return str(value)


def coerce_int(value: Any) -> int | None:
    """Coerce a value to ``int`` when possible."""

    if value is None or value == '':
        return None
    return int(value)
