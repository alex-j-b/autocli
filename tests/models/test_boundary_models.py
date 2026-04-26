from __future__ import annotations

import pytest
from pydantic import ValidationError

from autocli.models import (
    CommandFileModel,
    FixtureMetaFileModel,
    FixtureRequestFileModel,
    FixtureResponseFileModel,
    ProcessorContextModel,
    validate_approved_golden,
)


def build_command_file() -> dict[str, object]:
    return {
        "version": 1,
        "command": {
            "id": "get__h_www_rimi_ee__s_products__p_p1",
            "cli_path": ["products", "get"],
            "summary": "Get a product by id",
            "description": "Fetch one product payload from the live endpoint.",
            "arguments": [
                {
                    "name": "product-id",
                    "python_name": "product_id",
                    "kind": "argument",
                    "type": "string",
                    "required": True,
                    "help": "Recorded product identifier.",
                },
                {
                    "name": "format",
                    "python_name": "format",
                    "kind": "option",
                    "type": "string",
                    "required": False,
                    "default": "json",
                    "choices": ["json", "table"],
                    "help": "Response rendering mode.",
                },
            ],
            "request_mapping": {
                "request.params.p1": "args.product_id",
                "request.query.format": "args.format",
            },
            "request": {
                "method": "GET",
                "url_template": "https://www.rimi.ee/api/products/{p1}",
                "path_template": "/api/products/{p1}",
                "path_shape": [
                    {"kind": "literal", "value": "api"},
                    {"kind": "literal", "value": "products"},
                    {"kind": "parameter", "value": "p1"},
                ],
                "params": {},
                "query": {"lang": "en"},
                "headers": {"accept": "application/json"},
                "cookies": {},
                "body": None,
                "query_schema": {"type": "object"},
                "headers_schema": {"type": "object"},
                "body_schema": {"type": "object"},
            },
            "processors": {
                "pre": "processors.pre",
                "post": "processors.post",
            },
            "fixtures": [
                {
                    "id": "products_get_001",
                    "path": "fixtures/products_get_001",
                }
            ],
            "goldens": [
                {
                    "id": "products_get_001",
                    "path": "goldens/products_get_001.json",
                }
            ],
        },
    }


def build_fixture_request() -> dict[str, object]:
    return {
        "method": "GET",
        "url": "https://www.rimi.ee/api/products/123",
        "path": "/api/products/123",
        "query": {"lang": "en"},
        "headers": {"accept": "application/json"},
    }


def build_fixture_response() -> dict[str, object]:
    return {
        "status": 200,
        "headers": {"content-type": "application/json"},
    }


def build_fixture_meta() -> dict[str, object]:
    return {
        "command_id": "get__h_www_rimi_ee__s_products__p_p1",
        "captured_at": "2026-04-10T09:15:00Z",
        "raw_ref": "raw/products_get_001.flow",
        "flow_id": "entry-001",
    }


def build_processor_context() -> dict[str, object]:
    return {
        "phase": "post",
        "execution_mode": "fixture",
        "raw_mode": False,
        "command": {
            "id": "get__h_www_rimi_ee__s_products__p_p1",
            "cli_path": ["products", "get"],
            "summary": "Get a product by id",
        },
        "args": {"product_id": "123", "format": "json"},
        "request": {
            "method": "GET",
            "url": "https://www.rimi.ee/api/products/123",
            "path": "/api/products/123",
            "params": {"p1": "123"},
            "query": {"lang": "en"},
            "headers": {"accept": "application/json"},
            "cookies": {},
            "body": None,
            "trace_id": "abc123",
        },
        "response": {
            "status": 200,
            "headers": {"content-type": "application/json"},
            "cookies": {},
            "body": {"id": "123", "name": "Milk"},
            "elapsed_ms": 41,
        },
        "fixture": {
            "id": "products_get_001",
            "captured_at": "2026-04-10T09:15:00Z",
            "raw_ref": "raw/products_get_001.flow",
            "flow_id": "entry-001",
            "source": "flow",
        },
        "state": {"normalized": True},
        "output": {"id": "123", "name": "Milk"},
        "site_slug": "rimi-ee",
    }


def test_command_file_model_accepts_plan_shape() -> None:
    model = CommandFileModel.model_validate(build_command_file())

    assert model.version == 1
    assert model.command.id == "get__h_www_rimi_ee__s_products__p_p1"
    assert model.command.arguments[0].python_name == "product_id"
    assert model.command.request.path_shape[2].kind == "parameter"
    assert model.command.processors.pre == "processors.pre"


def test_fixture_file_models_accept_valid_envelopes_and_meta() -> None:
    request = FixtureRequestFileModel.model_validate(build_fixture_request())
    response = FixtureResponseFileModel.model_validate(build_fixture_response())
    meta = FixtureMetaFileModel.model_validate(build_fixture_meta())

    assert request.path == "/api/products/123"
    assert response.status == 200
    assert meta.raw_ref == "raw/products_get_001.flow"


def test_validate_approved_golden_accepts_plain_json() -> None:
    golden = validate_approved_golden(
        {
            "items": [{"id": "123", "name": "Milk"}],
            "count": 1,
            "ok": True,
        }
    )

    assert golden["count"] == 1


def test_processor_context_model_accepts_plan_shape() -> None:
    context = ProcessorContextModel.model_validate(build_processor_context())

    assert context.phase == "post"
    assert context.request.headers["accept"] == "application/json"
    assert context.output == {"id": "123", "name": "Milk"}


def test_command_file_requires_documented_fields() -> None:
    payload = build_command_file()
    del payload["command"]["summary"]

    with pytest.raises(ValidationError):
        CommandFileModel.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pre", "processors/pre.py"),
        ("post", "shared.post"),
    ],
)
def test_command_file_rejects_invalid_processor_refs(field: str, value: str) -> None:
    payload = build_command_file()
    payload["command"]["processors"][field] = value

    with pytest.raises(ValidationError):
        CommandFileModel.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["command"]["arguments"].append(
            {
                "name": "product-id",
                "python_name": "product_id_2",
                "kind": "option",
                "type": "string",
                "required": False,
            }
        ),
        lambda payload: payload["command"]["arguments"].append(
            {
                "name": "dry-run",
                "python_name": "dry_run",
                "kind": "argument",
                "type": "boolean",
                "required": False,
            }
        ),
        lambda payload: payload["command"]["arguments"].append(
            {
                "name": "limit",
                "python_name": "limit",
                "kind": "option",
                "type": "integer",
                "required": True,
                "default": 10,
            }
        ),
    ],
)
def test_command_file_rejects_invalid_argument_definitions(mutate) -> None:
    payload = build_command_file()
    mutate(payload)

    with pytest.raises(ValidationError):
        CommandFileModel.model_validate(payload)


@pytest.mark.parametrize(
    "mapping",
    [
        {"request.params": "args.product_id"},
        {
            "request.body": {"productCode": "123"},
            "request.body.productCode": "args.product_id",
        },
        {"request.query.format": "args.missing"},
    ],
)
def test_command_file_rejects_invalid_request_mappings(mapping: dict[str, object]) -> None:
    payload = build_command_file()
    payload["command"]["request_mapping"] = mapping

    with pytest.raises(ValidationError):
        CommandFileModel.model_validate(payload)


@pytest.mark.parametrize(
    ("builder", "mutator"),
    [
        (build_fixture_request, lambda payload: payload.pop("path")),
        (build_fixture_response, lambda payload: payload.__setitem__("status", 700)),
        (build_fixture_meta, lambda payload: payload.__setitem__("raw_ref", "/tmp/raw.json")),
    ],
)
def test_fixture_boundary_models_reject_invalid_envelopes(builder, mutator) -> None:
    payload = builder()
    mutator(payload)

    model_class = {
        build_fixture_request: FixtureRequestFileModel,
        build_fixture_response: FixtureResponseFileModel,
        build_fixture_meta: FixtureMetaFileModel,
    }[builder]

    with pytest.raises(ValidationError):
        model_class.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["command"]["goldens"].append(
            {"id": "products_get_001", "path": "goldens/products_get_001-copy.json"}
        ),
        lambda payload: payload["command"]["goldens"].__setitem__(
            0, {"id": "products_get_999", "path": "goldens/products_get_999.json"}
        ),
        lambda payload: payload["command"]["goldens"].__setitem__(
            0, {"id": "products_get_001", "path": "goldens/products_get_001.yaml"}
        ),
    ],
)
def test_command_file_rejects_invalid_goldens(mutate) -> None:
    payload = build_command_file()
    mutate(payload)

    with pytest.raises(ValidationError):
        CommandFileModel.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("phase", "during"),
        lambda payload: payload.pop("request"),
        lambda payload: payload.__setitem__("output", object()),
    ],
)
def test_processor_context_model_rejects_malformed_context(mutate) -> None:
    payload = build_processor_context()
    mutate(payload)

    with pytest.raises(ValidationError):
        ProcessorContextModel.model_validate(payload)
