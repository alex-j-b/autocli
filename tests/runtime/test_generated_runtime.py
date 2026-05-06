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

from tests.support import build_workspace, make_exchange, run_module, run_workspace_pytest

EMPTY_PLAYWRIGHT_HEADERS_JSON = json.dumps({'headers': {}}, separators=(',', ':'))


def read_command_complete(command_dir: Path) -> bool:
    payload = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
    return bool(payload['command'].get('complete'))


def install_json_processors_and_goldens(command_dir: Path, *, output_fields: list[str]) -> None:
    (command_dir / 'processors' / 'pre.py').write_text(
        'from __future__ import annotations\n\n\ndef run(context: dict[str, object]) -> dict[str, object]:\n    return context\n',
        encoding='utf-8',
    )

    post_lines = [
        'from __future__ import annotations',
        '',
        'import json',
        '',
        '',
        'def run(context: dict[str, object]) -> dict[str, object]:',
        "    body = context['response']['body']",
        "    payload = json.loads(body if isinstance(body, str) else body.decode('utf-8'))",
        "    context['output'] = {",
    ]
    for field in output_fields:
        post_lines.append(f"        '{field}': payload['{field}'],")
    post_lines.extend(
        [
            '    }',
            '    return context',
            '',
        ]
    )
    (command_dir / 'processors' / 'post.py').write_text('\n'.join(post_lines), encoding='utf-8')

    command_file = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
    for golden_ref in command_file['command']['goldens']:
        fixture_id = golden_ref['id']
        fixture_response_body = (command_dir / 'fixtures' / fixture_id / 'response.body').read_text(encoding='utf-8')
        payload = json.loads(fixture_response_body)
        golden_payload = {field: payload[field] for field in output_fields}
        (command_dir / golden_ref['path']).write_text(json.dumps(golden_payload, indent=2) + '\n', encoding='utf-8')


def install_fake_keyring_backend(workspace: Path, *, read_path: Path, write_path: Path) -> dict[str, str]:
    (workspace / 'fake_keyring_backend.py').write_text(
        '\n'.join(
            [
                'from __future__ import annotations',
                '',
                'import os',
                'from pathlib import Path',
                '',
                'from keyring.backend import KeyringBackend',
                '',
                '',
                'class FileKeyring(KeyringBackend):',
                '    priority = 1',
                '',
                '    def get_password(self, service: str, username: str) -> str | None:',
                "        path = Path(os.environ['AUTOCLI_FAKE_KEYRING_READ'])",
                '        if not path.exists():',
                '            return None',
                "        return path.read_text(encoding='utf-8')",
                '',
                '    def set_password(self, service: str, username: str, password: str) -> None:',
                "        Path(os.environ['AUTOCLI_FAKE_KEYRING_WRITE']).write_text(password, encoding='utf-8')",
                '',
                '    def delete_password(self, service: str, username: str) -> None:',
                '        raise NotImplementedError',
                '',
            ]
        ),
        encoding='utf-8',
    )
    return {
        'PYTHON_KEYRING_BACKEND': 'fake_keyring_backend.FileKeyring',
        'AUTOCLI_FAKE_KEYRING_READ': str(read_path),
        'AUTOCLI_FAKE_KEYRING_WRITE': str(write_path),
    }


def rewrite_cli_path(command_dir: Path, cli_path: list[str]) -> None:
    command_file = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
    command_file['command']['cli_path'] = cli_path
    (command_dir / 'command.yaml').write_text(yaml.safe_dump(command_file, sort_keys=False), encoding='utf-8')


def mark_command_complete(command_dir: Path) -> None:
    command_file = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
    command_file['command']['complete'] = True
    (command_dir / 'command.yaml').write_text(yaml.safe_dump(command_file, sort_keys=False), encoding='utf-8')


class EchoCartServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self._build_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _build_handler(self):
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def do_PUT(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                raw_body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                body = json.loads(raw_body.decode('utf-8'))
                item_id = parsed.path.rstrip('/').split('/')[-1]
                parent.requests.append(
                    {
                        'path': parsed.path,
                        'query': parse_qs(parsed.query),
                        'body': body,
                        'headers': dict(self.headers),
                    }
                )
                payload = {
                    'id': item_id,
                    'format': parse_qs(parsed.query).get('format', [None])[0],
                    'delta': body['delta'],
                    'mode': body['mode'],
                }
                response = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response)))
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
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange(
                'GET', 'https://shop.example.com/api/products/123', source_id='1', response_body=b'{"id":"123"}'
            ),
            make_exchange(
                'GET', 'https://shop.example.com/api/products/456', source_id='2', response_body=b'{"id":"456"}'
            ),
        ],
    )

    module_name = str(result['site_module'])
    help_result = run_module(workspace, module_name, ['--help'])
    assert help_result.returncode == 0
    assert 'products' not in help_result.stdout
    assert 'reason=incomplete' not in help_result.stderr

    command_dir = workspace / 'commands' / 'get__h_shop_example_com__s_api__s_products__p_p1'
    assert read_command_complete(command_dir) is False
    pytest_result = run_workspace_pytest(workspace, command_dir / 'tests' / 'test_command.py')
    assert pytest_result.returncode != 0
    assert read_command_complete(command_dir) is False


def test_generated_runtime_treats_missing_complete_flag_as_hidden(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange(
                'GET', 'https://shop.example.com/api/products/123', source_id='1', response_body=b'{"id":"123"}'
            ),
            make_exchange(
                'GET', 'https://shop.example.com/api/products/456', source_id='2', response_body=b'{"id":"456"}'
            ),
        ],
    )

    module_name = str(result['site_module'])
    command_dir = workspace / 'commands' / 'get__h_shop_example_com__s_api__s_products__p_p1'
    install_json_processors_and_goldens(command_dir, output_fields=['id'])

    payload = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
    payload['command'].pop('complete', None)
    (command_dir / 'command.yaml').write_text(yaml.safe_dump(payload, sort_keys=False), encoding='utf-8')

    help_result = run_module(workspace, module_name, ['--help'])
    assert help_result.returncode == 0
    assert 'products' not in help_result.stdout
    assert 'reason=command-file' not in help_result.stderr
    assert 'reason=incomplete' not in help_result.stderr


def test_generated_runtime_fixture_tests_replay_through_generated_cli_with_live_headers(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange(
                'GET', 'https://shop.example.com/api/products/123', source_id='1', response_body=b'{"id":"123"}'
            ),
            make_exchange(
                'GET', 'https://shop.example.com/api/products/456', source_id='2', response_body=b'{"id":"456"}'
            ),
        ],
    )

    command_dir = workspace / 'commands' / result['created_command_ids'][0]
    install_json_processors_and_goldens(command_dir, output_fields=['id'])

    pytest_result = run_workspace_pytest(
        workspace,
        command_dir / 'tests' / 'test_command.py',
        extra_env={'PLAYWRIGHT_HEADERS_JSON': EMPTY_PLAYWRIGHT_HEADERS_JSON},
    )

    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
    assert read_command_complete(command_dir) is True


def test_generated_runtime_fixture_tests_do_not_need_auth_header_configuration(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange(
                'GET', 'https://shop.example.com/api/products/123', source_id='1', response_body=b'{"id":"123"}'
            ),
            make_exchange(
                'GET', 'https://shop.example.com/api/products/456', source_id='2', response_body=b'{"id":"456"}'
            ),
        ],
    )

    command_dir = workspace / 'commands' / result['created_command_ids'][0]
    install_json_processors_and_goldens(command_dir, output_fields=['id'])

    pytest_result = run_workspace_pytest(workspace, command_dir / 'tests' / 'test_command.py')

    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
    assert not (workspace / '.env').exists()
    assert not (workspace / '.env.example').exists()
    assert read_command_complete(command_dir) is True


def test_generated_runtime_auth_instructions_prints_authenticate_skill(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange(
                'GET', 'https://shop.example.com/api/products/123', source_id='1', response_body=b'{"id":"123"}'
            ),
            make_exchange(
                'GET', 'https://shop.example.com/api/products/456', source_id='2', response_body=b'{"id":"456"}'
            ),
        ],
    )
    module_name = str(result['site_module'])
    skill_text = (workspace / 'skills' / 'authenticate' / 'SKILL.md').read_text(encoding='utf-8')

    instructions_result = run_module(workspace, module_name, ['auth', 'instructions'])

    assert instructions_result.returncode == 0, instructions_result.stderr
    assert instructions_result.stdout == skill_text
    assert 'skills/authenticate/references' in instructions_result.stdout
    assert 'await request.allHeaders()' in instructions_result.stdout


def test_generated_runtime_executes_live_request_mapping_and_raw_output(tmp_path: Path) -> None:
    server = EchoCartServer()
    server.start()
    try:
        workspace = tmp_path / 'workspace'
        base_url = f'http://127.0.0.1:{server.port}'
        result = build_workspace(
            workspace,
            [
                make_exchange(
                    'PUT',
                    f'{base_url}/epood/cart/change/123?format=json',
                    request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    request_body=b'{"delta": 1, "mode": "soft"}',
                    response_body=b'{"delta":1,"format":"json","id":"123","mode":"soft"}',
                    source_id='1',
                ),
                make_exchange(
                    'PUT',
                    f'{base_url}/epood/cart/change/456?format=table',
                    request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    request_body=b'{"delta": 2, "mode": "soft"}',
                    response_body=b'{"delta":2,"format":"table","id":"456","mode":"soft"}',
                    source_id='2',
                ),
            ],
        )

        module_name = str(result['site_module'])
        command_dir = workspace / 'commands' / result['created_command_ids'][0]
        install_json_processors_and_goldens(command_dir, output_fields=['id', 'format', 'delta', 'mode'])

        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / 'tests' / 'test_command.py',
            extra_env={'PLAYWRIGHT_HEADERS_JSON': EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
        assert read_command_complete(command_dir) is True

        help_result = run_module(workspace, module_name, ['--help'])
        assert help_result.returncode == 0, help_result.stderr
        assert 'cart' in help_result.stdout
        assert 'reason=incomplete' not in help_result.stderr

        playwright_headers = {
            'url': f'{base_url}/some/other/xhr',
            'method': 'GET',
            'resourceType': 'xhr',
            'capturedAt': '2026-04-24T20:46:23.572Z',
            'headers': {
                ':authority': 'ignored.example.com',
                ':method': 'GET',
                ':path': '/some/other/xhr',
                ':scheme': 'https',
                'accept': 'text/html',
                'cookie': 'foo=bar; baz=qux',
                'x-xsrf-token': 'token-123',
            },
        }
        env = {'PLAYWRIGHT_HEADERS_JSON': json.dumps(playwright_headers, separators=(',', ':'))}
        live_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3'],
            env=env,
        )
        assert live_result.returncode == 0, live_result.stderr
        assert json.loads(live_result.stdout) == {
            'delta': 3,
            'format': 'json',
            'id': '789',
            'mode': 'soft',
        }

        assert server.requests[-1]['path'] == '/epood/cart/change/789'
        assert server.requests[-1]['query'] == {'format': ['json']}
        assert server.requests[-1]['body'] == {'delta': 3, 'mode': 'soft'}
        assert server.requests[-1]['headers']['x-xsrf-token'] == 'token-123'
        assert server.requests[-1]['headers']['cookie'] == 'foo=bar; baz=qux'
        assert server.requests[-1]['headers']['accept'] == 'application/json'
        assert ':authority' not in server.requests[-1]['headers']

        raw_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3', '--raw'],
            env=env,
        )
        assert raw_result.returncode == 0, raw_result.stderr
        assert raw_result.stdout == '{"delta":3,"format":"json","id":"789","mode":"soft"}'

        raw_output_path = workspace / 'raw-output.json'
        raw_file_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3', '--raw', '--output', str(raw_output_path)],
            env=env,
        )
        assert raw_file_result.returncode == 0, raw_file_result.stderr
        assert raw_file_result.stdout == ''
        assert raw_output_path.read_text(encoding='utf-8') == '{"delta":3,"format":"json","id":"789","mode":"soft"}'

        replay_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3', '--replay'],
            env=env,
        )
        assert replay_result.returncode != 0
        assert '--replay is only available when AUTOCLI_TEST_MODE=true' in replay_result.stderr
    finally:
        server.stop()


def test_generated_runtime_preprocessor_headers_override_live_auth_headers(tmp_path: Path) -> None:
    server = EchoCartServer()
    server.start()
    try:
        workspace = tmp_path / 'workspace'
        base_url = f'http://127.0.0.1:{server.port}'
        result = build_workspace(
            workspace,
            [
                make_exchange(
                    'PUT',
                    f'{base_url}/epood/cart/change/123?format=json',
                    request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    request_body=b'{"delta": 1, "mode": "soft"}',
                    response_body=b'{"delta":1,"format":"json","id":"123","mode":"soft"}',
                    source_id='1',
                ),
                make_exchange(
                    'PUT',
                    f'{base_url}/epood/cart/change/456?format=table',
                    request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    request_body=b'{"delta": 2, "mode": "soft"}',
                    response_body=b'{"delta":2,"format":"table","id":"456","mode":"soft"}',
                    source_id='2',
                ),
            ],
        )

        module_name = str(result['site_module'])
        command_dir = workspace / 'commands' / result['created_command_ids'][0]
        install_json_processors_and_goldens(command_dir, output_fields=['id', 'format', 'delta', 'mode'])

        command_file = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
        command_file['command']['request']['headers']['x-xsrf-token'] = 'token-from-static'
        (command_dir / 'command.yaml').write_text(yaml.safe_dump(command_file, sort_keys=False), encoding='utf-8')
        (command_dir / 'processors' / 'pre.py').write_text(
            '\n'.join(
                [
                    'from __future__ import annotations',
                    '',
                    '',
                    'def run(context: dict[str, object]) -> dict[str, object]:',
                    "    request = context['request']",
                    '    assert isinstance(request, dict)',
                    "    headers = request['headers']",
                    '    assert isinstance(headers, dict)',
                    "    headers['x-xsrf-token'] = 'token-from-pre'",
                    '    return context',
                    '',
                ]
            ),
            encoding='utf-8',
        )
        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / 'tests' / 'test_command.py',
            extra_env={'PLAYWRIGHT_HEADERS_JSON': EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

        playwright_headers = {
            'url': f'{base_url}/checkout/xhr',
            'method': 'GET',
            'resourceType': 'xhr',
            'capturedAt': '2026-04-24T20:46:23.572Z',
            'headers': {
                'cookie': 'from-env',
                'x-xsrf-token': 'token-from-env',
            },
        }
        live_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3'],
            env={'PLAYWRIGHT_HEADERS_JSON': json.dumps(playwright_headers, separators=(',', ':'))},
        )

        assert live_result.returncode == 0, live_result.stderr
        assert server.requests[-1]['headers']['x-xsrf-token'] == 'token-from-pre'
        assert server.requests[-1]['headers']['cookie'] == 'from-env'
    finally:
        server.stop()


def test_generated_runtime_loads_playwright_headers_from_keyring_with_env_override(tmp_path: Path) -> None:
    server = EchoCartServer()
    server.start()
    try:
        workspace = tmp_path / 'workspace'
        base_url = f'http://127.0.0.1:{server.port}'
        result = build_workspace(
            workspace,
            [
                make_exchange(
                    'PUT',
                    f'{base_url}/epood/cart/change/123?format=json',
                    request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    request_body=b'{"delta": 1, "mode": "soft"}',
                    response_body=b'{"delta":1,"format":"json","id":"123","mode":"soft"}',
                    source_id='1',
                ),
                make_exchange(
                    'PUT',
                    f'{base_url}/epood/cart/change/456?format=table',
                    request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    request_body=b'{"delta": 2, "mode": "soft"}',
                    response_body=b'{"delta":2,"format":"table","id":"456","mode":"soft"}',
                    source_id='2',
                ),
            ],
        )

        module_name = str(result['site_module'])
        command_dir = workspace / 'commands' / result['created_command_ids'][0]
        install_json_processors_and_goldens(command_dir, output_fields=['id', 'format', 'delta', 'mode'])
        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / 'tests' / 'test_command.py',
            extra_env={'PLAYWRIGHT_HEADERS_JSON': EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

        keyring_headers = {
            'url': f'{base_url}/checkout/xhr',
            'method': 'GET',
            'resourceType': 'xhr',
            'capturedAt': '2026-04-24T20:46:23.572Z',
            'headers': {
                'cookie': 'from=keyring',
                'x-xsrf-token': 'token-from-keyring',
            },
        }
        keyring_file = tmp_path / 'keyring-secret.json'
        keyring_file.write_text(json.dumps(keyring_headers, separators=(',', ':')), encoding='utf-8')
        fake_env = install_fake_keyring_backend(
            workspace,
            read_path=keyring_file,
            write_path=tmp_path / 'stored-secret.json',
        )

        live_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3'],
            env=fake_env,
        )
        assert live_result.returncode == 0, live_result.stderr
        assert json.loads(live_result.stdout) == {
            'delta': 3,
            'format': 'json',
            'id': '789',
            'mode': 'soft',
        }
        assert server.requests[-1]['headers']['x-xsrf-token'] == 'token-from-keyring'
        assert server.requests[-1]['headers']['cookie'] == 'from=keyring'

        shell_headers = {
            'url': f'{base_url}/checkout/xhr',
            'method': 'GET',
            'resourceType': 'xhr',
            'capturedAt': '2026-04-24T20:46:23.572Z',
            'headers': {
                'cookie': 'from=shell',
                'x-xsrf-token': 'token-from-shell',
            },
        }
        live_result = run_module(
            workspace,
            module_name,
            ['cart', 'change', '789', '--format', 'json', '--delta', '3'],
            env=fake_env | {'PLAYWRIGHT_HEADERS_JSON': json.dumps(shell_headers, separators=(',', ':'))},
        )
        assert live_result.returncode == 0, live_result.stderr
        assert server.requests[-1]['headers']['x-xsrf-token'] == 'token-from-shell'
        assert server.requests[-1]['headers']['cookie'] == 'from=shell'

        store_input = tmp_path / 'store-input.json'
        store_input.write_text(json.dumps(shell_headers, separators=(',', ':')), encoding='utf-8')
        store_result = subprocess.run(
            [sys.executable, '-m', module_name, 'auth', 'store-headers', '--file', str(store_input)],
            cwd=workspace,
            env=os.environ.copy()
            | {
                'PYTHONPATH': str(workspace) + os.pathsep + os.environ.get('PYTHONPATH', ''),
                **fake_env,
            },
            capture_output=True,
            text=True,
        )
        assert store_result.returncode == 0, store_result.stderr
        assert 'Stored authenticated header configuration in the system keyring' in store_result.stdout
        assert 'token-from-shell' not in store_result.stdout
        assert 'from=shell' not in store_result.stdout
        assert (tmp_path / 'stored-secret.json').read_text(encoding='utf-8').strip() == json.dumps(
            shell_headers,
            separators=(',', ':'),
        )
    finally:
        server.stop()


def test_generated_runtime_rejects_duplicate_cli_paths_after_validation(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange(
                'GET', 'https://shop.example.com/api/alpha/123', source_id='1', response_body=b'{"id":"123"}'
            ),
            make_exchange(
                'GET', 'https://shop.example.com/api/alpha/456', source_id='2', response_body=b'{"id":"456"}'
            ),
            make_exchange('GET', 'https://shop.example.com/api/beta/123', source_id='3', response_body=b'{"id":"123"}'),
            make_exchange('GET', 'https://shop.example.com/api/beta/456', source_id='4', response_body=b'{"id":"456"}'),
        ],
    )

    module_name = str(result['site_module'])
    command_dirs = [workspace / 'commands' / command_id for command_id in result['created_command_ids']]
    for command_dir in command_dirs:
        install_json_processors_and_goldens(command_dir, output_fields=['id'])
        pytest_result = run_workspace_pytest(
            workspace,
            command_dir / 'tests' / 'test_command.py',
            extra_env={'PLAYWRIGHT_HEADERS_JSON': EMPTY_PLAYWRIGHT_HEADERS_JSON},
        )
        assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

    for command_dir in command_dirs:
        rewrite_cli_path(command_dir, ['dup'])

    help_result = run_module(workspace, module_name, ['--help'])
    assert help_result.returncode == 0
    assert 'dup' not in help_result.stdout
    assert 'reason=duplicate-cli-path' in help_result.stderr


def test_generated_runtime_help_lists_descendant_commands(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    result = build_workspace(
        workspace,
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1', response_body=b'{"id":"123"}'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2', response_body=b'{"id":"456"}'),
            make_exchange(
                'GET',
                'https://shop.example.com/api/products/123/reviews',
                source_id='3',
                response_body=b'{"id":"123"}',
            ),
            make_exchange(
                'GET',
                'https://shop.example.com/api/products/456/reviews',
                source_id='4',
                response_body=b'{"id":"456"}',
            ),
            make_exchange('GET', 'https://shop.example.com/api/orders/123', source_id='5', response_body=b'{"id":"123"}'),
            make_exchange('GET', 'https://shop.example.com/api/orders/456', source_id='6', response_body=b'{"id":"456"}'),
        ],
    )

    module_name = str(result['site_module'])
    command_dirs = [workspace / 'commands' / command_id for command_id in result['created_command_ids']]
    for command_dir in command_dirs:
        install_json_processors_and_goldens(command_dir, output_fields=['id'])
        mark_command_complete(command_dir)

    command_by_path = {
        yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))['command']['request']['path_template']: command_dir
        for command_dir in command_dirs
    }
    rewrite_cli_path(command_by_path['/api/products/{p1}'], ['products', 'get'])
    rewrite_cli_path(command_by_path['/api/products/{p1}/reviews'], ['products', 'reviews', 'list'])
    rewrite_cli_path(command_by_path['/api/orders/{p1}'], ['orders', 'get'])

    root_help = run_module(workspace, module_name, ['--help'])
    assert root_help.returncode == 0, root_help.stderr
    assert 'products get' in root_help.stdout
    assert 'products reviews list' in root_help.stdout
    assert 'orders get' in root_help.stdout
    assert 'auth store-headers' in root_help.stdout

    products_help = run_module(workspace, module_name, ['products', '--help'])
    assert products_help.returncode == 0, products_help.stderr
    assert 'get' in products_help.stdout
    assert 'reviews list' in products_help.stdout
    assert 'orders get' not in products_help.stdout

    command_help = run_module(workspace, module_name, ['products', 'reviews', 'list', '--help'])
    assert command_help.returncode == 0, command_help.stderr
    assert '--replay' not in command_help.stdout

    replay_result = run_module(
        workspace,
        module_name,
        ['products', 'reviews', 'list', '123', '--replay'],
        env={'AUTOCLI_TEST_MODE': 'true'},
    )
    assert replay_result.returncode == 0, replay_result.stderr
    assert json.loads(replay_result.stdout) == {'id': '123'}
