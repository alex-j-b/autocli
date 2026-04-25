from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from mitmproxy import connection, http, io
from typer.testing import CliRunner

from autocli.capture import normalize_exchange
from autocli.cli import app
from autocli.compiler.schema import compile_command_candidates
from autocli.models import CommandFileModel, FixtureMetaFileModel, FixtureRequestFileModel, FixtureResponseFileModel
from autocli.scaffold import bootstrap_workspace
from autocli.scaffold.render import render_agents_md, render_build_cli_skill


def make_exchange(
    method: str,
    url: str,
    *,
    request_headers: dict[str, str] | None = None,
    request_body: bytes = b"",
    response_headers: dict[str, str] | None = None,
    response_body: bytes = b'{"ok": true}',
    status: int = 200,
    source_id: str = "1",
) -> dict[str, object]:
    return normalize_exchange(
        {
            "source": {
                "format": "flow",
                "source_path": "/tmp/sample.flow",
                "capture_id": source_id,
                "captured_at": "2026-04-11T09:15:00Z",
            },
            "request": {
                "method": method,
                "url": url,
                "headers": request_headers or {},
                "body": request_body,
            },
            "response": {
                "status": status,
                "headers": response_headers or {"Content-Type": "application/json"},
                "body": response_body,
            },
        }
    )


def build_compiled_commands(exchanges: list[dict[str, object]]) -> list[dict[str, object]]:
    return compile_command_candidates(exchanges)


def write_flow_capture(path: Path, exchanges: list[dict[str, object]]) -> None:
    with path.open("wb") as handle:
        writer = io.FlowWriter(handle)
        for exchange in exchanges:
            request = exchange["request"]
            response = exchange["response"]
            flow = http.HTTPFlow(
                client_conn=connection.Client(peername=("127.0.0.1", 1111), sockname=("127.0.0.1", 8080)),
                server_conn=connection.Server(address=(request["host"], request["port"])),
            )
            flow.request = http.Request.make(
                request["method"],
                request["url"],
                content=bytes(request["body"]),
                headers=request["headers"],
            )
            flow.response = http.Response.make(
                int(response["status"]),
                content=bytes(response["body"]),
                headers=response["headers"],
            )
            writer.add(flow)


def test_bootstrap_workspace_creates_canonical_structure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    compiled_commands = build_compiled_commands(
        [
            make_exchange(
                "PUT",
                "https://shop.example.com/epood/cart/change/123?format=json&lang=en",
                request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                request_body=b'{"delta": 1, "mode": "soft"}',
                source_id="1",
            ),
            make_exchange(
                "PUT",
                "https://shop.example.com/epood/cart/change/456?format=table&lang=en&include=totals",
                request_headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cookie": "session=secret",
                    "X-XSRF-Token": "token-123",
                },
                request_body=b'{"delta": 2, "mode": "soft"}',
                source_id="2",
            ),
        ]
    )

    result = bootstrap_workspace(workspace, compiled_commands=compiled_commands)

    assert result["site_slug"] == "shop-example-com"
    assert result["site_module"] == "shop_example_com"
    assert result["created_command_ids"] == ["put__h_shop_example_com__s_epood__s_cart__s_change__p_p1"]

    pyproject = tomllib.loads((workspace / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "example"
    assert pyproject["project"]["description"] == "Generated CLI workspace for example"
    assert pyproject["project"]["scripts"] == {
        "example": "shop_example_com.cli:app",
    }
    assert pyproject["tool"]["autocli"] == {
        "schema_version": 1,
        "site_slug": "shop-example-com",
        "site_module": "shop_example_com",
        "primary_hosts": ["shop.example.com"],
        "command_root": "commands",
        "shared_package": "shared",
    }

    site_dir = workspace / "shop_example_com"
    agents_path = workspace / "AGENTS.md"
    build_cli_skill_path = workspace / "skills" / "build-cli" / "SKILL.md"
    assert (workspace / "shared" / "__init__.py").exists()
    assert (workspace / "commands" / "__init__.py").exists()
    assert (workspace / ".env").read_text(encoding="utf-8") == 'PLAYWRIGHT_HEADERS_JSON={"headers":{}}\n'
    assert (workspace / ".env.example").read_text(encoding="utf-8") == 'PLAYWRIGHT_HEADERS_JSON={"headers":{}}\n'
    assert agents_path.exists()
    assert build_cli_skill_path.exists()
    assert (site_dir / "__init__.py").exists()
    assert (site_dir / "__main__.py").exists()
    assert (site_dir / "cli.py").exists()
    assert (site_dir / "runtime.py").exists()
    assert (site_dir / "testing.py").exists()

    command_dir = workspace / "commands" / "put__h_shop_example_com__s_epood__s_cart__s_change__p_p1"
    command_file = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
    validated_command = CommandFileModel.model_validate(command_file)
    assert validated_command.command.cli_path == ["cart", "change"]
    assert validated_command.command.fixtures[0].id == "cart_change_001"
    assert len(validated_command.command.fixtures) == 1
    assert validated_command.command.goldens[0].path == "goldens/cart_change_001.json"
    assert "cookie" not in {header.lower() for header in validated_command.command.request.headers}
    assert "x-xsrf-token" not in {header.lower() for header in validated_command.command.request.headers}

    fixture_dir = command_dir / "fixtures" / "cart_change_001"
    request = FixtureRequestFileModel.model_validate(json.loads((fixture_dir / "request.json").read_text(encoding="utf-8")))
    FixtureResponseFileModel.model_validate(json.loads((fixture_dir / "response.json").read_text(encoding="utf-8")))
    meta = FixtureMetaFileModel.model_validate(json.loads((fixture_dir / "meta.json").read_text(encoding="utf-8")))
    assert meta.raw_ref is None
    assert request.url == "https://shop.example.com/epood/cart/change/456?format=table&lang=en&include=totals"
    assert "cookie" not in {header.lower() for header in request.headers}
    assert "x-xsrf-token" not in {header.lower() for header in request.headers}
    assert (fixture_dir / "request.body").read_bytes() == b'{"delta": 2, "mode": "soft"}'
    assert (fixture_dir / "response.body").read_bytes() == b'{"ok": true}'
    assert not (command_dir / "raw").exists()
    assert (command_dir / "goldens").is_dir()

    generated_test = (command_dir / "tests" / "test_command.py").read_text(encoding="utf-8")
    assert "from shop_example_com.testing import run_command_contract" in generated_test
    assert "autocli" not in generated_test

    runtime_source = (site_dir / "runtime.py").read_text(encoding="utf-8")
    assert "def build_app(workspace_root: Path) -> typer.Typer:" in runtime_source
    testing_source = (site_dir / "testing.py").read_text(encoding="utf-8")
    assert "def run_command_contract(command_dir: Path) -> None:" in testing_source
    assert agents_path.read_text(encoding="utf-8") == render_agents_md(
        site_module="shop_example_com",
        cli_name="example",
    )
    assert build_cli_skill_path.read_text(encoding="utf-8") == render_build_cli_skill()


def test_bootstrap_workspace_is_append_only_on_rerun(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    initial_commands = build_compiled_commands(
        [
            make_exchange("GET", "https://shop.example.com/api/products/123", source_id="1"),
            make_exchange("GET", "https://shop.example.com/api/products/456", source_id="2"),
        ]
    )
    bootstrap_workspace(workspace, compiled_commands=initial_commands)

    existing_command_dir = workspace / "commands" / "get__h_shop_example_com__s_api__s_products__p_p1"
    pre_stub = existing_command_dir / "processors" / "pre.py"
    pre_stub.write_text("custom pre-processor\n", encoding="utf-8")

    rerun_commands = build_compiled_commands(
        [
            make_exchange("GET", "https://shop.example.com/api/products/123", source_id="1"),
            make_exchange("GET", "https://shop.example.com/api/products/456", source_id="2"),
            make_exchange("GET", "https://shop.example.com/api/inventory/123/full", source_id="3"),
            make_exchange("GET", "https://shop.example.com/api/inventory/456/full", source_id="4"),
        ]
    )
    result = bootstrap_workspace(workspace, compiled_commands=rerun_commands)

    assert result["created_command_ids"] == ["get__h_shop_example_com__s_api__s_inventory__p_p1__s_full"]
    assert result["skipped_command_ids"] == ["get__h_shop_example_com__s_api__s_products__p_p1"]
    assert any("get__h_shop_example_com__s_api__s_products__p_p1" in warning for warning in result["warnings"])
    assert pre_stub.read_text(encoding="utf-8") == "custom pre-processor\n"
    assert len(list((existing_command_dir / "fixtures").iterdir())) == 1
    assert (workspace / "AGENTS.md").exists()
    assert (workspace / "skills" / "build-cli" / "SKILL.md").exists()
    assert (workspace / ".env").exists()
    assert (workspace / ".env.example").exists()
    assert (
        workspace / "commands" / "get__h_shop_example_com__s_api__s_inventory__p_p1__s_full" / "command.yaml"
    ).exists()


def test_bootstrap_workspace_rejects_ambiguous_initial_host(tmp_path: Path) -> None:
    compiled_commands = build_compiled_commands(
        [
            make_exchange("GET", "https://a.example.com/api/items/1", source_id="1"),
            make_exchange("GET", "https://a.example.com/api/items/2", source_id="2"),
            make_exchange("GET", "https://b.example.com/api/items/1", source_id="3"),
            make_exchange("GET", "https://b.example.com/api/items/2", source_id="4"),
        ]
    )

    with pytest.raises(ValueError, match=r"a\.example\.com=2, b\.example\.com=2"):
        bootstrap_workspace(tmp_path / "workspace", compiled_commands=compiled_commands)


def test_record_command_generates_workspace_from_flow(tmp_path: Path) -> None:
    capture_path = tmp_path / "capture.flow"
    write_flow_capture(
        capture_path,
        [
            {
                "request": {
                    "method": "GET",
                    "url": "https://shop.example.com/api/products/123",
                    "host": "shop.example.com",
                    "port": 443,
                    "headers": {"Accept": "application/json"},
                    "body": b"",
                },
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": b'{"id":"123"}',
                },
            },
            {
                "request": {
                    "method": "GET",
                    "url": "https://shop.example.com/api/products/456",
                    "host": "shop.example.com",
                    "port": 443,
                    "headers": {"Accept": "application/json"},
                    "body": b"",
                },
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": b'{"id":"456"}',
                },
            },
        ],
    )

    runner = CliRunner()
    output_dir = tmp_path / "generated"
    result = runner.invoke(app, ["build", str(capture_path), "--output-dir", str(output_dir)])

    assert result.exit_code == 0, result.output
    assert "created 1 command(s), skipped 0 duplicate(s)." in result.output
    assert f"Next: uv tool install -e {output_dir.resolve()}" in result.output
    assert f"Next: use refinement skill {output_dir.resolve() / 'skills' / 'build-cli' / 'SKILL.md'}" in result.output
    assert (output_dir / "commands" / "get__h_shop_example_com__s_api__s_products__p_p1" / "command.yaml").exists()


def test_build_ignores_unsupported_capture_file(tmp_path: Path) -> None:
    capture_path = tmp_path / "capture.json"
    capture_path.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["build", str(capture_path), "--output-dir", str(tmp_path / "generated")])

    assert result.exit_code != 0
    assert "No command-bearing exchanges were accepted from the capture." in result.output
