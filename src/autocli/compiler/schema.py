"""Schema and CLI inference helpers."""

from __future__ import annotations

import copy
import re
from typing import Any

from autocli.capture.normalize import decode_body_bytes


def compile_command_candidates(exchanges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compile normalized accepted exchanges into command candidates."""

    from autocli.compiler.grouping import group_exchanges

    return [infer_command_schema(group) for group in group_exchanges(exchanges)]


def infer_command_schema(grouped_exchange: dict[str, Any]) -> dict[str, Any]:
    """Infer shallow transport schema and first-pass CLI arguments."""

    samples = list(grouped_exchange["samples"])
    request_headers = base_request_headers(samples)
    query_schema = infer_object_schema(
        [coerce_scalar_mapping(sample["request"]["query"]) for sample in samples],
        parse_string_values=True,
    )
    headers_schema = infer_object_schema(
        [coerce_scalar_mapping(sample["request"]["headers"]) for sample in samples],
        parse_string_values=False,
    )

    decoded_bodies = [decode_body_bytes(sample["request"]["body"], sample["request"].get("media_type")) for sample in samples]
    body_objects = [body for body in decoded_bodies if isinstance(body, dict)]
    body_schema = infer_object_schema(body_objects, parse_string_values=True) if body_objects else infer_non_object_body_schema(decoded_bodies)

    base_query: dict[str, Any] = {}
    base_body: dict[str, Any] | str | int | float | bool | None = {} if body_objects else copy.deepcopy(decoded_bodies[0])
    arguments: list[dict[str, Any]] = []
    request_mapping: dict[str, Any] = {}

    path_argument_defs, path_request_mapping = infer_path_arguments(grouped_exchange)
    arguments.extend(path_argument_defs)
    request_mapping.update(path_request_mapping)

    query_inference = infer_scalar_mapping_fields(
        [coerce_scalar_mapping(sample["request"]["query"]) for sample in samples],
        target_prefix="request.query",
    )
    arguments.extend(query_inference["arguments"])
    request_mapping.update(query_inference["request_mapping"])

    if body_objects:
        body_inference = infer_body_fields(body_objects)
        arguments.extend(body_inference["arguments"])
        request_mapping.update(body_inference["request_mapping"])
        base_body = body_inference["base"]

    return {
        "id": grouped_exchange["command_id"],
        "cli_path": list(grouped_exchange["cli_path"]),
        "summary": grouped_exchange["summary"],
        "cli_path_conflict": grouped_exchange["cli_path_conflict"],
        "samples": list(grouped_exchange["samples"]),
        "request": {
            "method": grouped_exchange["method"].upper(),
            "url_template": grouped_exchange["url_template"],
            "path_template": grouped_exchange["path_template"],
            "path_shape": copy.deepcopy(grouped_exchange["path_shape"]),
            "params": {},
            "query": base_query,
            "headers": request_headers,
            "cookies": {},
            "body": base_body,
            "query_schema": query_schema,
            "headers_schema": headers_schema,
            "body_schema": body_schema,
        },
        "arguments": arguments,
        "request_mapping": request_mapping,
    }


def infer_path_arguments(grouped_exchange: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Infer positional arguments from path parameters."""

    arguments: list[dict[str, Any]] = []
    request_mapping: dict[str, Any] = {}
    path_shape = list(grouped_exchange["path_shape"])
    path_samples = [
        [segment for segment in sample["canonical"]["path_segments"]]
        for sample in grouped_exchange["samples"]
    ]

    for index, segment in enumerate(path_shape):
        if segment["kind"] != "parameter":
            continue
        values = [parse_scalar_value(sample_segments[index]) for sample_segments in path_samples]
        argument_type = infer_argument_type(values)
        python_name = segment["value"]
        arguments.append(
            {
                "name": python_name.replace("_", "-"),
                "python_name": python_name,
                "kind": "argument",
                "type": argument_type,
                "required": True,
                "help": f"Path parameter {python_name}.",
            }
        )
        request_mapping[f"request.params.{python_name}"] = f"args.{python_name}"
    return arguments, request_mapping


def infer_scalar_mapping_fields(samples: list[dict[str, Any]], *, target_prefix: str) -> dict[str, Any]:
    """Infer option arguments and literal mappings from scalar request fields."""

    field_names = sorted({key for sample in samples for key in sample})
    arguments: list[dict[str, Any]] = []
    request_mapping: dict[str, Any] = {}

    for field_name in field_names:
        observed = []
        missing = False
        repeated = False
        for sample in samples:
            if field_name not in sample:
                missing = True
                continue
            value = sample[field_name]
            if isinstance(value, list):
                repeated = True
                break
            observed.append(parse_scalar_value(value))
        if repeated or not observed:
            continue

        distinct_values = distinct_preserving_order(observed)
        if len(distinct_values) == 1 and not missing:
            request_mapping[f"{target_prefix}.{field_name}"] = distinct_values[0]
            continue

        option_name, python_name = make_argument_names(field_name)
        argument: dict[str, Any] = {
            "name": option_name,
            "python_name": python_name,
            "kind": "option",
            "type": infer_argument_type(observed),
            "required": not missing,
            "help": f"{field_name} request value.",
        }
        arguments.append(argument)
        request_mapping[f"{target_prefix}.{field_name}"] = f"args.{python_name}"

    return {
        "arguments": deduplicate_arguments(arguments),
        "request_mapping": request_mapping,
        "base": {},
    }


def infer_body_fields(bodies: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer option arguments and literal mappings from JSON/form body leaves."""

    flattened_bodies = [flatten_scalar_leaves(body) for body in bodies]
    field_names = sorted({key for body in flattened_bodies for key in body})
    arguments: list[dict[str, Any]] = []
    request_mapping: dict[str, Any] = {}

    for field_name in field_names:
        observed = []
        missing = False
        invalid = False
        for body in flattened_bodies:
            if field_name not in body:
                missing = True
                continue
            value = body[field_name]
            if isinstance(value, (dict, list)):
                invalid = True
                break
            observed.append(parse_scalar_value(value))
        if invalid or not observed:
            continue

        distinct_values = distinct_preserving_order(observed)
        target = f"request.body.{field_name}"
        if len(distinct_values) == 1 and not missing:
            request_mapping[target] = distinct_values[0]
            continue

        option_name, python_name = make_argument_names(field_name)
        arguments.append(
            {
                "name": option_name,
                "python_name": python_name,
                "kind": "option",
                "type": infer_argument_type(observed),
                "required": not missing,
                "help": f"{field_name} request body value.",
            }
        )
        request_mapping[target] = f"args.{python_name}"

    return {
        "arguments": deduplicate_arguments(arguments),
        "request_mapping": request_mapping,
        "base": {},
    }


def base_request_headers(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a literal base header set for the request template."""

    representative_headers = dict(samples[0]["request"]["headers"])
    for blocked_header in ("content-length", "cookie", "host"):
        representative_headers.pop(blocked_header, None)
    return representative_headers


def infer_object_schema(samples: list[dict[str, Any]], *, parse_string_values: bool) -> dict[str, Any]:
    """Infer a shallow object schema."""

    properties: dict[str, dict[str, Any]] = {}
    additional_properties = False

    for sample in samples:
        if not isinstance(sample, dict):
            additional_properties = True
            continue
        for key, value in sample.items():
            if isinstance(value, list):
                additional_properties = True
                continue
            if isinstance(value, dict):
                properties.setdefault(key, {"type": "object"})
                additional_properties = True
                continue

            inferred_type = infer_scalar_schema_type(parse_scalar_value(value) if parse_string_values else value)
            current = properties.get(key)
            if current is None:
                properties[key] = {"type": inferred_type}
                continue
            if current["type"] != inferred_type:
                if {current["type"], inferred_type} <= {"integer", "number"}:
                    current["type"] = "number"
                else:
                    additional_properties = True

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    schema["additionalProperties"] = additional_properties
    return schema


def infer_non_object_body_schema(bodies: list[Any]) -> dict[str, Any] | None:
    """Infer a non-object body schema when all bodies are scalar-like."""

    observed = [body for body in bodies if body is not None]
    if not observed:
        return None
    inferred_types = {infer_scalar_schema_type(body) for body in observed if not isinstance(body, (dict, list, bytes))}
    if not inferred_types:
        if any(isinstance(body, bytes) for body in observed):
            return {"type": "string", "format": "binary"}
        return None
    if len(inferred_types) == 1:
        return {"type": inferred_types.pop()}
    if inferred_types <= {"integer", "number"}:
        return {"type": "number"}
    return {"type": "string"}


def coerce_scalar_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Drop repeated values so direct-v1 inference only sees scalar fields."""

    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, list):
            continue
        result[key] = value
    return result


def flatten_scalar_leaves(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested object leaves into dotted paths."""

    flattened: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            flattened.update(flatten_scalar_leaves(child, path))
        elif isinstance(child, list):
            continue
        else:
            flattened[path] = child
    return flattened


def parse_scalar_value(value: Any) -> Any:
    """Convert string-like values into richer scalar types when safe."""

    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            return value
    return value


def infer_argument_type(values: list[Any]) -> str:
    """Infer the command argument type from sample values."""

    inferred_types = {infer_scalar_schema_type(value) for value in values}
    if inferred_types == {"boolean"}:
        return "boolean"
    if inferred_types == {"integer"}:
        return "integer"
    if inferred_types <= {"integer", "number"}:
        return "number"
    return "string"


def infer_scalar_schema_type(value: Any) -> str:
    """Infer a JSON-schema-like scalar type."""

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def make_argument_names(field_name: str) -> tuple[str, str]:
    """Convert a field path into CLI and Python names."""

    option_name = field_name.replace(".", "-").replace("_", "-")
    option_name = re.sub(r"[^a-z0-9-]+", "-", option_name.lower()).strip("-")
    python_name = option_name.replace("-", "_")
    return option_name, python_name


def deduplicate_arguments(arguments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure inferred arguments have unique option and python names."""

    seen_option_names: set[str] = set()
    seen_python_names: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for argument in arguments:
        if argument["name"] in seen_option_names or argument["python_name"] in seen_python_names:
            continue
        seen_option_names.add(argument["name"])
        seen_python_names.add(argument["python_name"])
        deduplicated.append(argument)
    return deduplicated


def distinct_preserving_order(values: list[Any]) -> list[Any]:
    """Return distinct values while preserving first-seen order."""

    distinct: list[Any] = []
    for value in values:
        if value not in distinct:
            distinct.append(value)
    return distinct
