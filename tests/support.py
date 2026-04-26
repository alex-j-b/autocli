from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mitmproxy import connection, http, io

from autocli.capture import normalize_exchange
from autocli.compiler.schema import compile_command_candidates
from autocli.scaffold import bootstrap_workspace


def make_exchange(
    method: str,
    url: str,
    *,
    request_headers: dict[str, str] | None = None,
    request_body: bytes = b'',
    response_headers: dict[str, str] | None = None,
    response_body: bytes = b'{"ok": true}',
    status: int = 200,
    source_id: str = '1',
    captured_at: str = '2026-04-11T09:15:00Z',
) -> dict[str, Any]:
    return normalize_exchange(
        {
            'source': {
                'format': 'flow',
                'source_path': '/tmp/sample.flow',
                'capture_id': source_id,
                'captured_at': captured_at,
            },
            'request': {
                'method': method,
                'url': url,
                'headers': request_headers or {},
                'body': request_body,
            },
            'response': {
                'status': status,
                'headers': response_headers or {'Content-Type': 'application/json'},
                'body': response_body,
            },
        }
    )


def build_compiled_commands(exchanges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return compile_command_candidates(exchanges)


def build_workspace(workspace: Path, exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    compiled_commands = build_compiled_commands(exchanges)
    return bootstrap_workspace(workspace, compiled_commands=compiled_commands)


def run_module(
    workspace: Path,
    module_name: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-m', module_name, *args],
        cwd=workspace,
        env=_workspace_env(workspace, env),
        capture_output=True,
        text=True,
    )


def run_workspace_pytest(
    workspace: Path,
    target: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-m', 'pytest', str(target), '-q'],
        cwd=workspace,
        env=_workspace_env(workspace, extra_env),
        capture_output=True,
        text=True,
    )


def write_flow_capture(path: Path, exchanges: list[dict[str, Any]]) -> None:
    with path.open('wb') as handle:
        writer = io.FlowWriter(handle)
        for exchange in exchanges:
            request = exchange['request']
            response = exchange['response']
            flow = http.HTTPFlow(
                client_conn=connection.Client(peername=('127.0.0.1', 1111), sockname=('127.0.0.1', 8080)),
                server_conn=connection.Server(address=(request['host'], request['port'])),
            )
            flow.request = http.Request.make(
                request['method'],
                request['url'],
                content=bytes(request['body']),
                headers=request['headers'],
            )
            flow.response = http.Response.make(
                int(response['status']),
                content=bytes(response['body']),
                headers=response['headers'],
            )
            writer.add(flow)


def _workspace_env(workspace: Path, extra_env: dict[str, str] | None) -> dict[str, str]:
    command_env = os.environ.copy()
    command_env['PYTHONPATH'] = str(workspace) + os.pathsep + command_env.get('PYTHONPATH', '')
    if extra_env:
        command_env.update(extra_env)
    return command_env
