"""Endpoint grouping helpers."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import unquote, urlsplit

from autocli.capture.normalize import DEFAULT_PORTS

ACTION_LEAVES = {
    'activate',
    'add',
    'attach',
    'change',
    'checkout',
    'create',
    'delete',
    'detach',
    'get',
    'list',
    'login',
    'logout',
    'remove',
    'search',
    'set',
    'submit',
    'update',
    'validate',
}
COMMON_PREFIXES = {'api', 'rest', 'service', 'services', 'v1', 'v2', 'v3', 'v4'}
REST_COLLISION_ACTIONS = {
    ('get', 'collection'): 'list',
    ('get', 'detail'): 'get',
    ('post', 'collection'): 'create',
    ('put', 'detail'): 'update',
    ('patch', 'detail'): 'update',
    ('delete', 'detail'): 'delete',
}
UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
HEX_TOKEN_RE = re.compile(r'^[0-9a-f]{8,}$', re.IGNORECASE)
NUMBER_RE = re.compile(r'^\d+$')
VERSION_RE = re.compile(r'^v\d+$')


def group_exchanges(exchanges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group accepted exchanges into command candidates."""

    preliminary_buckets: dict[tuple[str, str, int | None, int], list[dict[str, Any]]] = defaultdict(list)
    for exchange in exchanges:
        canonical = build_canonical_exchange(exchange)
        canonical_data = canonical['canonical']
        preliminary_buckets[
            (
                canonical_data['method'],
                canonical_data['host'],
                canonical_data['port'],
                len(canonical_data['path_segments']),
            )
        ].append(canonical)

    grouped: list[dict[str, Any]] = []
    for bucket in preliminary_buckets.values():
        signature_buckets: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for exchange in bucket:
            signature_buckets[path_signature(exchange['canonical']['path_segments'])].append(exchange)
        for signature_group in signature_buckets.values():
            grouped.append(build_group(signature_group))

    grouped.sort(key=lambda group: (group['host'], group['method'], group['path_template'], group['command_id']))
    ensure_unique_command_ids(grouped)
    assign_cli_paths(grouped)
    return grouped


def build_canonical_exchange(exchange: dict[str, Any]) -> dict[str, Any]:
    """Add canonical path-first grouping fields to a normalized exchange."""

    request = exchange['request']
    parsed = urlsplit(request['url'])
    method = str(request['method']).lower()
    host = str(request['host']).lower()
    scheme = str(request['scheme']).lower()
    raw_port = int(request['port'])
    port = None if raw_port == DEFAULT_PORTS.get(scheme) else raw_port
    path = normalize_path(parsed.path or str(request['path']))
    path_segments = split_path(path)

    canonical = dict(exchange)
    canonical['canonical'] = {
        'method': method,
        'host': host,
        'scheme': scheme,
        'port': port,
        'path': path,
        'path_segments': path_segments,
    }
    return canonical


def normalize_path(path: str) -> str:
    """Normalize a URL path for grouping."""

    normalized = path or '/'
    if not normalized.startswith('/'):
        normalized = f'/{normalized}'
    if normalized != '/' and normalized.endswith('/'):
        normalized = normalized.rstrip('/')
    return normalized or '/'


def split_path(path: str) -> list[str]:
    """Split a normalized path into unquoted segments."""

    if path == '/':
        return []
    return [unquote(segment) for segment in path.strip('/').split('/') if segment]


def path_signature(path_segments: list[str]) -> tuple[str, ...]:
    """Compute a conservative merge signature for a path."""

    signature: list[str] = []
    for segment in path_segments:
        normalized = normalize_cli_token(segment)
        if looks_like_parameter_segment(normalized):
            signature.append('<var>')
        else:
            signature.append(normalized)
    return tuple(signature)


def looks_like_parameter_segment(segment: str) -> bool:
    """Heuristic for identifier-like path segments."""

    if not segment or segment in ACTION_LEAVES:
        return False
    if NUMBER_RE.fullmatch(segment):
        return True
    if UUID_RE.fullmatch(segment):
        return True
    if HEX_TOKEN_RE.fullmatch(segment):
        return True
    if len(segment) >= 8 and any(character.isdigit() for character in segment):
        return True
    if len(segment) >= 12 and re.fullmatch(r'[A-Za-z0-9_-]+', segment):
        return True
    return False


def build_group(exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one grouped endpoint candidate."""

    representative = min(
        exchanges,
        key=lambda exchange: (
            exchange['request']['url'],
            capture_sort_key(exchange['source']['capture_id']),
        ),
    )
    method = representative['canonical']['method']
    host = representative['canonical']['host']
    scheme = representative['canonical']['scheme']
    port = representative['canonical']['port']
    segment_matrix = [exchange['canonical']['path_segments'] for exchange in exchanges]

    path_shape: list[dict[str, str]] = []
    path_parts: list[str] = []
    parameter_count = 1
    varying_positions = 0
    for values in zip(*segment_matrix, strict=False):
        unique_values = list(dict.fromkeys(values))
        if len(unique_values) == 1:
            segment_value = unique_values[0]
            path_shape.append({'kind': 'literal', 'value': segment_value})
            path_parts.append(segment_value)
            continue

        varying_positions += 1
        parameter_name = f'p{parameter_count}'
        parameter_count += 1
        path_shape.append({'kind': 'parameter', 'value': parameter_name})
        path_parts.append(f'{{{parameter_name}}}')

    if varying_positions and varying_positions == len(path_shape):
        raise ValueError('path grouping collapsed into an all-parameter template')

    path_template = '/' + '/'.join(path_parts) if path_parts else '/'
    url_template = build_url_template(scheme, host, port, path_template)
    command_id = build_command_id(method, host, port, path_shape)

    return {
        'method': method,
        'host': host,
        'scheme': scheme,
        'port': port,
        'path_template': path_template,
        'path_shape': path_shape,
        'url_template': url_template,
        'command_id': command_id,
        'samples': sorted(
            exchanges,
            key=lambda exchange: (
                exchange['request']['url'],
                capture_sort_key(exchange['source']['capture_id']),
            ),
        ),
    }


def build_url_template(scheme: str, host: str, port: int | None, path_template: str) -> str:
    """Render a canonical URL template."""

    if port is None:
        return f'{scheme}://{host}{path_template}'
    return f'{scheme}://{host}:{port}{path_template}'


def build_command_id(
    method: str,
    host: str,
    port: int | None,
    path_shape: list[dict[str, str]],
) -> str:
    """Build the stable technical command id."""

    segments = [method, f'h_{sanitize_command_token(host)}']
    if port is not None:
        segments.append(f'port_{port}')
    for segment in path_shape:
        if segment['kind'] == 'literal':
            segments.append(f's_{sanitize_command_token(segment["value"])}')
        else:
            segments.append(f'p_{segment["value"]}')
    return '__'.join(segments)


def sanitize_command_token(value: str) -> str:
    """Normalize a token for use inside ``command.id``."""

    normalized = normalize_cli_token(value).replace('-', '_')
    return re.sub(r'[^a-z0-9_]+', '_', normalized).strip('_') or 'root'


def normalize_cli_token(value: str) -> str:
    """Normalize a path token into lowercase kebab-case."""

    text = unquote(value)
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', text)
    text = text.replace('_', '-').replace(' ', '-')
    text = re.sub(r'[^A-Za-z0-9-]+', '-', text)
    text = re.sub(r'-{2,}', '-', text)
    return text.strip('-').lower()


def ensure_unique_command_ids(groups: list[dict[str, Any]]) -> None:
    """Reject duplicate generated command ids."""

    command_id_counts = Counter(group['command_id'] for group in groups)
    duplicates = sorted(command_id for command_id, count in command_id_counts.items() if count > 1)
    if duplicates:
        duplicates_text = ', '.join(duplicates)
        raise ValueError(f'duplicate generated command ids: {duplicates_text}')


def assign_cli_paths(groups: list[dict[str, Any]]) -> None:
    """Assign final cli paths with deterministic collision handling."""

    leading_segment_counts = Counter()
    for group in groups:
        literals = literal_segments(group['path_shape'])
        if literals:
            leading_segment_counts[(group['host'], normalize_cli_token(literals[0]))] += 1

    for group in groups:
        normalized_literals = prepare_cli_literals(group, leading_segment_counts)
        group['cli_literals'] = normalized_literals
        group['cli_path'] = derive_base_cli_path(group, normalized_literals)

    resolve_cli_collisions(groups)
    for group in groups:
        group['summary'] = build_summary(group)


def prepare_cli_literals(group: dict[str, Any], leading_segment_counts: Counter[tuple[str, str]]) -> list[str]:
    """Prepare normalized literal path segments for cli derivation."""

    literals = [normalize_cli_token(segment) for segment in literal_segments(group['path_shape'])]
    while len(literals) > 1:
        first = literals[0]
        if first in COMMON_PREFIXES or VERSION_RE.fullmatch(first):
            literals = literals[1:]
            continue
        if leading_segment_counts[(group['host'], first)] >= 2 and len(literals) > 2:
            literals = literals[1:]
            continue
        break
    return literals


def literal_segments(path_shape: list[dict[str, str]]) -> list[str]:
    """Return only literal path-shape values."""

    return [segment['value'] for segment in path_shape if segment['kind'] == 'literal']


def derive_base_cli_path(group: dict[str, Any], literals: list[str]) -> list[str]:
    """Derive the shortest initial cli path candidate."""

    if not literals:
        return ['request']
    if len(literals) == 1:
        return [literals[0]]
    if literals[-1] in ACTION_LEAVES:
        return [literals[-2], literals[-1]]
    return [literals[-2], literals[-1]]


def resolve_cli_collisions(groups: list[dict[str, Any]]) -> None:
    """Resolve cli_path collisions without opaque numeric suffixes."""

    collisions = cli_collisions(groups)
    if collisions:
        for candidate_groups in collisions.values():
            for group in candidate_groups:
                group['cli_path'] = rest_style_cli_path(group)

    collisions = cli_collisions(groups)
    if collisions:
        for candidate_groups in collisions.values():
            for group in candidate_groups:
                group['cli_path'] = expand_cli_path(group)

    collisions = cli_collisions(groups)
    for group in groups:
        group['cli_path_conflict'] = tuple(group['cli_path']) in collisions


def cli_collisions(groups: list[dict[str, Any]]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    """Return colliding cli paths."""

    candidates: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        candidates[tuple(group['cli_path'])].append(group)
    return {path: items for path, items in candidates.items() if len(items) > 1}


def rest_style_cli_path(group: dict[str, Any]) -> list[str]:
    """Use REST-style method disambiguation for common collisions."""

    literals = list(group['cli_literals'])
    if not literals:
        return list(group['cli_path'])
    if literals[-1] in ACTION_LEAVES:
        return list(group['cli_path'])

    resource = literals[-1]
    shape = classify_rest_shape(group)
    action = REST_COLLISION_ACTIONS.get((group['method'], shape))
    if not action:
        return list(group['cli_path'])
    if action == 'list' and list(group['cli_path']) == [resource]:
        return [resource, action]
    if action != 'list':
        return [resource, action]
    return list(group['cli_path'])


def classify_rest_shape(group: dict[str, Any]) -> str:
    """Classify a grouped endpoint as collection or detail."""

    path_shape = group['path_shape']
    if path_shape and path_shape[-1]['kind'] == 'parameter':
        return 'detail'
    return 'collection'


def expand_cli_path(group: dict[str, Any]) -> list[str]:
    """Expand a cli path by one more meaningful parent literal segment."""

    literals = list(group['cli_literals'])
    if len(literals) <= 1:
        return list(group['cli_path'])

    current = list(group['cli_path'])
    synthetic_leaf = current[-1] in REST_COLLISION_ACTIONS.values()
    if synthetic_leaf:
        resource = current[0]
        if resource in literals:
            resource_index = literals.index(resource)
            if resource_index > 0:
                return [literals[resource_index - 1], *current]
        return current

    if len(current) >= len(literals):
        return current
    return [literals[-3], *current] if len(literals) >= 3 else [literals[0], *current]


def build_summary(group: dict[str, Any]) -> str:
    """Build a short operator-facing summary from the final cli path."""

    cli_path = list(group['cli_path'])
    if len(cli_path) > 1 and cli_path[-1] in ACTION_LEAVES:
        action = cli_path[-1].replace('-', ' ').title()
        resource = ' '.join(segment.replace('-', ' ') for segment in cli_path[:-1])
        return f'{action} {resource}'.strip()

    resource_text = ' '.join(segment.replace('-', ' ') for segment in cli_path)
    if group['method'] == 'get':
        if classify_rest_shape(group) == 'detail':
            return f'Get {resource_text}'
        return f'List {resource_text}'
    if group['method'] == 'post' and len(cli_path) == 1:
        return f'Create {resource_text}'
    return resource_text.title()


def capture_sort_key(capture_id: str) -> tuple[int, str]:
    """Sort capture ids numerically when they are digit-only."""

    if capture_id.isdigit():
        return (int(capture_id), capture_id)
    return (10**9, capture_id)
