from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from autocli.capture import normalize_exchange
from autocli.compiler.schema import compile_command_candidates
from autocli.scaffold import bootstrap_workspace

EMPTY_PLAYWRIGHT_HEADERS_JSON = json.dumps({"headers": {}}, separators=(",", ":"))


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
) -> dict[str, Any]:
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


def build_workspace(workspace: Path, exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    compiled_commands = compile_command_candidates(exchanges)
    return bootstrap_workspace(workspace, compiled_commands=compiled_commands)


def run_module(workspace: Path, module_name: str, args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env["PYTHONPATH"] = str(workspace) + os.pathsep + command_env.get("PYTHONPATH", "")
    if env:
        command_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", module_name, *args],
        cwd=workspace,
        env=command_env,
        capture_output=True,
        text=True,
    )


def run_workspace_pytest(
    workspace: Path,
    target: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env["PYTHONPATH"] = str(workspace) + os.pathsep + command_env.get("PYTHONPATH", "")
    if extra_env:
        command_env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q"],
        cwd=workspace,
        env=command_env,
        capture_output=True,
        text=True,
    )


def read_command_complete(command_dir: Path) -> bool:
    payload = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
    return bool(payload["command"].get("complete"))


def install_json_processors_and_goldens(command_dir: Path, *, output_fields: list[str]) -> None:
    (command_dir / "processors" / "pre.py").write_text(
        "from __future__ import annotations\n\n\ndef run(context: dict[str, object]) -> dict[str, object]:\n    return context\n",
        encoding="utf-8",
    )

    post_lines = [
        "from __future__ import annotations",
        "",
        "import json",
        "",
        "",
        "def run(context: dict[str, object]) -> dict[str, object]:",
        "    body = context['response']['body']",
        "    payload = json.loads(body if isinstance(body, str) else body.decode('utf-8'))",
        "    context['output'] = {",
    ]
    for field in output_fields:
        post_lines.append(f"        '{field}': payload['{field}'],")
    post_lines.extend(
        [
            "    }",
            "    return context",
            "",
        ]
    )
    (command_dir / "processors" / "post.py").write_text("\n".join(post_lines), encoding="utf-8")

    command_file = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
    for golden_ref in command_file["command"]["goldens"]:
        fixture_id = golden_ref["id"]
        fixture_response_body = (command_dir / "fixtures" / fixture_id / "response.body").read_text(encoding="utf-8")
        payload = json.loads(fixture_response_body)
        golden_payload = {field: payload[field] for field in output_fields}
        (command_dir / golden_ref["path"]).write_text(json.dumps(golden_payload, indent=2) + "\n", encoding="utf-8")


def rewrite_cli_path(command_dir: Path, cli_path: list[str]) -> None:
    command_file = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
    command_file["command"]["cli_path"] = cli_path
    (command_dir / "command.yaml").write_text(yaml.safe_dump(command_file, sort_keys=False), encoding="utf-8")


class EchoCartServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _build_handler(self):
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def do_PUT(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw_body.decode("utf-8"))
                item_id = parsed.path.rstrip("/").split("/")[-1]
                parent.requests.append(
                    {
                        "path": parsed.path,
                        "query": parse_qs(parsed.query),
                        "body": body,
                        "headers": dict(self.headers),
                    }
                )
                payload = {
                    "id": item_id,
                    "format": parse_qs(parsed.query).get("format", [None])[0],
                    "delta": body["delta"],
                    "mode": body["mode"],
                }
                response = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        return Handler

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def test_generated_runtime_requires_completed_commands_before_registration(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    result = build_workspace(
        workspace,
        [
            make_exchange("GET", "https://shop.example.com/api/products/123", source_id="1", response_body=b'{"id":"123"}'),
            make_exchange("GET", "https://shop.example.com/api/products/456", source_id="2", response_body=b'{"id":"456"}'),
        ],
    )

    module_name = str(result["site_module"])
    help_result = run_module(workspace, module_name, ["--help"])
    assert help_result.returncode == 0
    assert "products" not in help_result.stdout
    assert "reason=incomplete" not in help_result.stderr

    command_dir = workspace / "commands" / "get__h_shop_example_com__s_api__s_products__p_p1"
    assert read_command_complete(command_dir) is False
    pytest_result = run_workspace_pytest(workspace, command_dir / "tests" / "test_command.py")
    assert pytest_result.returncode != 0
    assert read_command_complete(command_dir) is False


def test_generated_runtime_treats_missing_complete_flag_as_hidden(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    result = build_workspace(
        workspace,
        [
            make_exchange("GET", "https://shop.example.com/api/products/123", source_id="1", response_body=b'{"id":"123"}'),
            make_exchange("GET", "https://shop.example.com/api/products/456", source_id="2", response_body=b'{"id":"456"}'),
        ],
    )

    module_name = str(result["site_module"])
    command_dir = workspace / "commands" / "get__h_shop_example_com__s_api__s_products__p_p1"
    install_json_processors_and_goldens(command_dir, output_fields=["id"])

    payload = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
    payload["command"].pop("complete", None)
    (command_dir / "command.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    help_result = run_module(workspace, module_name, ["--help"])
    assert help_result.returncode == 0
    assert "products" not in help_result.stdout
    assert "reason=command-file" not in help_result.stderr
    assert "reason=incomplete" not in help_result.stderr


def test_generated_runtime_fixture_tests_replay_through_generated_cli_with_live_headers(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    result = build_workspace(
        workspace,
        [
            make_exchange("GET", "https://shop.example.com/api/products/123", source_id="1", response_body=b'{"id":"123"}'),
            make_exchange("GET", "https://shop.example.com/api/products/456", source_id="2", response_body=b'{"id":"456"}'),
        ],
    )

    command_dir = workspace / "commands" / result["created_command_ids"][0]
    install_json_processors_and_goldens(command_dir, output_fields=["id"])

    pytest_result = run_workspace_pytest(
        workspace,
        command_dir / "tests" / "test_command.py",
        extra_env={"PLAYWRIGHT_HEADERS_JSON": EMPTY_PLAYWRIGHT_HEADERS_JSON},
    )

    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
    assert read_command_complete(command_dir) is True


def test_generated_runtime_fixture_tests_use_scaffolded_dotenv_placeholder(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    result = build_workspace(
        workspace,
        [
            make_exchange("GET", "https://shop.example.com/api/products/123", source_id="1", response_body=b'{"id":"123"}'),
            make_exchange("GET", "https://shop.example.com/api/products/456", source_id="2", response_body=b'{"id":"456"}'),
        ],
    )

    command_dir = workspace / "commands" / result["created_command_ids"][0]
    install_json_processors_and_goldens(command_dir, output_fields=["id"])

    pytest_result = run_workspace_pytest(workspace, command_dir / "tests" / "test_command.py")

    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
    assert (workspace / ".env").read_text(encoding="utf-8") == 'PLAYWRIGHT_HEADERS_JSON={"headers":{}}\n'
    assert read_command_complete(command_dir) is True


def test_generated_runtime_executes_live_request_mapping_and_raw_output(tmp_path: Path) -> None:
    server = EchoCartServer()
    server.start()
    try:
        workspace = tmp_path / "workspace"
        base_url = f"http://127.0.0.1:{server.port}"
        result = build_workspace(
            workspace,
            [
                make_exchange(
                    "PUT",
                    f"{base_url}/epood/cart/change/123?format=json",
                    request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                    request_body=b'{"delta": 1, "mode": "soft"}',
                    response_body=b'{"delta":1,"format":"json","id":"123","mode":"soft"}',
                    source_id="1",
                ),
                make_exchange(
                    "PUT",
                    f"{base_url}/epood/cart/change/456?format=table",
                    request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                    request_body=b'{"delta": 2, "mode": "soft"}',
                    response_body=b'{"delta":2,"format":"table","id":"456","mode":"soft"}',
                    source_id="2",
                ),
            ],
        )

        module_name = str(result["site_module"])
        command_dir = workspace / "commands" / result["created_command_ids"][0]
        install_json_processors_and_goldens(command_dir, output_fields=["id", "format", "delta", "mode"])

        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / "tests" / "test_command.py",
            extra_env={"PLAYWRIGHT_HEADERS_JSON": EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
        assert read_command_complete(command_dir) is True

        help_result = run_module(workspace, module_name, ["--help"])
        assert help_result.returncode == 0, help_result.stderr
        assert "cart" in help_result.stdout
        assert "reason=incomplete" not in help_result.stderr

        playwright_headers = {
            "url": f"{base_url}/some/other/xhr",
            "method": "GET",
            "resourceType": "xhr",
            "capturedAt": "2026-04-24T20:46:23.572Z",
            "headers": {
                ":authority": "ignored.example.com",
                ":method": "GET",
                ":path": "/some/other/xhr",
                ":scheme": "https",
                "accept": "text/html",
                "cookie": "foo=bar; baz=qux",
                "x-xsrf-token": "token-123",
            },
        }
        env = {"PLAYWRIGHT_HEADERS_JSON": json.dumps(playwright_headers, separators=(",", ":"))}
        live_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3"],
            env=env,
        )
        assert live_result.returncode == 0, live_result.stderr
        assert json.loads(live_result.stdout) == {
            "delta": 3,
            "format": "json",
            "id": "789",
            "mode": "soft",
        }

        assert server.requests[-1]["path"] == "/epood/cart/change/789"
        assert server.requests[-1]["query"] == {"format": ["json"]}
        assert server.requests[-1]["body"] == {"delta": 3, "mode": "soft"}
        assert server.requests[-1]["headers"]["x-xsrf-token"] == "token-123"
        assert server.requests[-1]["headers"]["cookie"] == "foo=bar; baz=qux"
        assert server.requests[-1]["headers"]["accept"] == "application/json"
        assert ":authority" not in server.requests[-1]["headers"]

        raw_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3", "--raw"],
            env=env,
        )
        assert raw_result.returncode == 0, raw_result.stderr
        assert raw_result.stdout == '{"delta":3,"format":"json","id":"789","mode":"soft"}'

        raw_output_path = workspace / "raw-output.json"
        raw_file_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3", "--raw", "--output", str(raw_output_path)],
            env=env,
        )
        assert raw_file_result.returncode == 0, raw_file_result.stderr
        assert raw_file_result.stdout == ""
        assert raw_output_path.read_text(encoding="utf-8") == '{"delta":3,"format":"json","id":"789","mode":"soft"}'

        replay_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3", "--replay"],
            env=env,
        )
        assert replay_result.returncode != 0
        assert "--replay is only available when AUTOCLI_TEST_MODE=true" in replay_result.stderr
    finally:
        server.stop()


def test_generated_runtime_preprocessor_headers_override_live_auth_headers(tmp_path: Path) -> None:
    server = EchoCartServer()
    server.start()
    try:
        workspace = tmp_path / "workspace"
        base_url = f"http://127.0.0.1:{server.port}"
        result = build_workspace(
            workspace,
            [
                make_exchange(
                    "PUT",
                    f"{base_url}/epood/cart/change/123?format=json",
                    request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                    request_body=b'{"delta": 1, "mode": "soft"}',
                    response_body=b'{"delta":1,"format":"json","id":"123","mode":"soft"}',
                    source_id="1",
                ),
                make_exchange(
                    "PUT",
                    f"{base_url}/epood/cart/change/456?format=table",
                    request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                    request_body=b'{"delta": 2, "mode": "soft"}',
                    response_body=b'{"delta":2,"format":"table","id":"456","mode":"soft"}',
                    source_id="2",
                ),
            ],
        )

        module_name = str(result["site_module"])
        command_dir = workspace / "commands" / result["created_command_ids"][0]
        install_json_processors_and_goldens(command_dir, output_fields=["id", "format", "delta", "mode"])

        command_file = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
        command_file["command"]["request"]["headers"]["x-xsrf-token"] = "token-from-static"
        (command_dir / "command.yaml").write_text(yaml.safe_dump(command_file, sort_keys=False), encoding="utf-8")
        (command_dir / "processors" / "pre.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "",
                    "def run(context: dict[str, object]) -> dict[str, object]:",
                    "    request = context['request']",
                    "    assert isinstance(request, dict)",
                    "    headers = request['headers']",
                    "    assert isinstance(headers, dict)",
                    "    headers['x-xsrf-token'] = 'token-from-pre'",
                    "    return context",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / "tests" / "test_command.py",
            extra_env={"PLAYWRIGHT_HEADERS_JSON": EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

        playwright_headers = {
            "url": f"{base_url}/checkout/xhr",
            "method": "GET",
            "resourceType": "xhr",
            "capturedAt": "2026-04-24T20:46:23.572Z",
            "headers": {
                "cookie": "from-env",
                "x-xsrf-token": "token-from-env",
            },
        }
        live_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3"],
            env={"PLAYWRIGHT_HEADERS_JSON": json.dumps(playwright_headers, separators=(",", ":"))},
        )

        assert live_result.returncode == 0, live_result.stderr
        assert server.requests[-1]["headers"]["x-xsrf-token"] == "token-from-pre"
        assert server.requests[-1]["headers"]["cookie"] == "from-env"
    finally:
        server.stop()


def test_generated_runtime_loads_playwright_headers_from_dotenv_with_shell_override(tmp_path: Path) -> None:
    server = EchoCartServer()
    server.start()
    try:
        workspace = tmp_path / "workspace"
        base_url = f"http://127.0.0.1:{server.port}"
        result = build_workspace(
            workspace,
            [
                make_exchange(
                    "PUT",
                    f"{base_url}/epood/cart/change/123?format=json",
                    request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                    request_body=b'{"delta": 1, "mode": "soft"}',
                    response_body=b'{"delta":1,"format":"json","id":"123","mode":"soft"}',
                    source_id="1",
                ),
                make_exchange(
                    "PUT",
                    f"{base_url}/epood/cart/change/456?format=table",
                    request_headers={"Content-Type": "application/json", "Accept": "application/json"},
                    request_body=b'{"delta": 2, "mode": "soft"}',
                    response_body=b'{"delta":2,"format":"table","id":"456","mode":"soft"}',
                    source_id="2",
                ),
            ],
        )

        module_name = str(result["site_module"])
        command_dir = workspace / "commands" / result["created_command_ids"][0]
        install_json_processors_and_goldens(command_dir, output_fields=["id", "format", "delta", "mode"])
        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / "tests" / "test_command.py",
            extra_env={"PLAYWRIGHT_HEADERS_JSON": EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

        dotenv_headers = {
            "url": f"{base_url}/checkout/xhr",
            "method": "GET",
            "resourceType": "xhr",
            "capturedAt": "2026-04-24T20:46:23.572Z",
            "headers": {
                "cookie": "from=dotenv",
                "x-xsrf-token": "token-from-dotenv",
            },
        }
        (workspace / ".env").write_text(
            "PLAYWRIGHT_HEADERS_JSON=" + json.dumps(dotenv_headers, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        live_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3"],
        )
        assert live_result.returncode == 0, live_result.stderr
        assert json.loads(live_result.stdout) == {
            "delta": 3,
            "format": "json",
            "id": "789",
            "mode": "soft",
        }
        assert server.requests[-1]["headers"]["x-xsrf-token"] == "token-from-dotenv"
        assert server.requests[-1]["headers"]["cookie"] == "from=dotenv"

        shell_headers = {
            "url": f"{base_url}/checkout/xhr",
            "method": "GET",
            "resourceType": "xhr",
            "capturedAt": "2026-04-24T20:46:23.572Z",
            "headers": {
                "cookie": "from=shell",
                "x-xsrf-token": "token-from-shell",
            },
        }
        live_result = run_module(
            workspace,
            module_name,
            ["cart", "change", "789", "--format", "json", "--delta", "3"],
            env={"PLAYWRIGHT_HEADERS_JSON": json.dumps(shell_headers, separators=(",", ":"))},
        )
        assert live_result.returncode == 0, live_result.stderr
        assert server.requests[-1]["headers"]["x-xsrf-token"] == "token-from-shell"
        assert server.requests[-1]["headers"]["cookie"] == "from=shell"
    finally:
        server.stop()


def test_generated_runtime_rejects_duplicate_cli_paths_after_validation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    result = build_workspace(
        workspace,
        [
            make_exchange("GET", "https://shop.example.com/api/alpha/123", source_id="1", response_body=b'{"id":"123"}'),
            make_exchange("GET", "https://shop.example.com/api/alpha/456", source_id="2", response_body=b'{"id":"456"}'),
            make_exchange("GET", "https://shop.example.com/api/beta/123", source_id="3", response_body=b'{"id":"123"}'),
            make_exchange("GET", "https://shop.example.com/api/beta/456", source_id="4", response_body=b'{"id":"456"}'),
        ],
    )

    module_name = str(result["site_module"])
    command_dirs = [workspace / "commands" / command_id for command_id in result["created_command_ids"]]
    for command_dir in command_dirs:
        install_json_processors_and_goldens(command_dir, output_fields=["id"])
        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / "tests" / "test_command.py",
            extra_env={"PLAYWRIGHT_HEADERS_JSON": EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

    for command_dir in command_dirs:
        rewrite_cli_path(command_dir, ["dup"])

    help_result = run_module(workspace, module_name, ["--help"])
    assert help_result.returncode == 0
    assert "dup" not in help_result.stdout
    assert "reason=duplicate-cli-path" in help_result.stderr
