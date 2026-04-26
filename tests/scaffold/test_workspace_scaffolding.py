from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from autocli.cli import app
from autocli.models import CommandFileModel, FixtureMetaFileModel, FixtureRequestFileModel, FixtureResponseFileModel
from autocli.scaffold import bootstrap_workspace
from autocli.scaffold.render import render_agents_md, render_build_cli_skill, render_workspace_gitignore
from tests.support import build_compiled_commands, make_exchange, write_flow_capture


def test_bootstrap_workspace_creates_canonical_structure(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    compiled_commands = build_compiled_commands(
        [
            make_exchange(
                'PUT',
                'https://shop.example.com/epood/cart/change/123?format=json&lang=en',
                request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                request_body=b'{"delta": 1, "mode": "soft"}',
                source_id='1',
            ),
            make_exchange(
                'PUT',
                'https://shop.example.com/epood/cart/change/456?format=table&lang=en&include=totals',
                request_headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Cookie': 'session=secret',
                    'X-XSRF-Token': 'token-123',
                },
                request_body=b'{"delta": 2, "mode": "soft"}',
                response_headers={
                    'Content-Type': 'application/json',
                    'Set-Cookie': 'session=secret; HttpOnly',
                    'X-Session-Id': 'session-123',
                    'X-CSRF-Token': 'csrf-123',
                },
                source_id='2',
            ),
        ]
    )

    result = bootstrap_workspace(workspace, compiled_commands=compiled_commands)

    assert result['site_slug'] == 'shop-example-com'
    assert result['site_module'] == 'shop_example_com'
    assert result['created_command_ids'] == ['put__h_shop_example_com__s_epood__s_cart__s_change__p_p1']

    pyproject = tomllib.loads((workspace / 'pyproject.toml').read_text(encoding='utf-8'))
    assert pyproject['project']['name'] == 'workspace'
    assert pyproject['project']['description'] == 'Generated CLI workspace for workspace'
    assert pyproject['project']['scripts'] == {
        'workspace': 'shop_example_com.cli:app',
    }
    assert pyproject['project']['dependencies'] == [
        'httpx>=0.27,<1',
        'msgpack>=1,<2',
        'pydantic>=2.8,<3',
        'python-dotenv>=1,<2',
        'PyYAML>=6,<7',
        'rich>=13.7,<14',
        'typer>=0.16,<1',
    ]
    assert pyproject['dependency-groups'] == {
        'dev': ['pytest>=8.3,<9'],
    }
    assert pyproject['tool']['autocli'] == {
        'schema_version': 1,
        'executable_name': 'workspace',
        'site_slug': 'shop-example-com',
        'site_module': 'shop_example_com',
        'primary_hosts': ['shop.example.com'],
        'command_root': 'commands',
        'shared_package': 'shared',
    }

    site_dir = workspace / 'shop_example_com'
    agents_path = workspace / 'AGENTS.md'
    build_cli_skill_path = workspace / 'skills' / 'build-cli' / 'SKILL.md'
    assert (workspace / 'shared' / '__init__.py').exists()
    assert (workspace / 'commands' / '__init__.py').exists()
    assert (workspace / '.gitignore').read_text(encoding='utf-8') == render_workspace_gitignore()
    assert (workspace / '.env').read_text(encoding='utf-8') == 'PLAYWRIGHT_HEADERS_JSON={"headers":{}}\n'
    assert (workspace / '.env.example').read_text(encoding='utf-8') == 'PLAYWRIGHT_HEADERS_JSON={"headers":{}}\n'
    assert agents_path.exists()
    assert build_cli_skill_path.exists()
    assert (site_dir / '__init__.py').exists()
    assert (site_dir / '__main__.py').exists()
    assert (site_dir / 'cli.py').exists()
    assert (site_dir / 'runtime.py').exists()
    assert (site_dir / 'testing.py').exists()

    command_dir = workspace / 'commands' / 'put__h_shop_example_com__s_epood__s_cart__s_change__p_p1'
    command_file = yaml.safe_load((command_dir / 'command.yaml').read_text(encoding='utf-8'))
    validated_command = CommandFileModel.model_validate(command_file)
    assert validated_command.command.cli_path == ['cart', 'change']
    assert validated_command.command.fixtures[0].id == 'cart_change_001'
    assert len(validated_command.command.fixtures) == 1
    assert validated_command.command.goldens[0].path == 'goldens/cart_change_001.json'
    assert 'cookie' not in {header.lower() for header in validated_command.command.request.headers}
    assert 'x-xsrf-token' not in {header.lower() for header in validated_command.command.request.headers}

    fixture_dir = command_dir / 'fixtures' / 'cart_change_001'
    request = FixtureRequestFileModel.model_validate(
        json.loads((fixture_dir / 'request.json').read_text(encoding='utf-8'))
    )
    response = FixtureResponseFileModel.model_validate(
        json.loads((fixture_dir / 'response.json').read_text(encoding='utf-8'))
    )
    meta_json = json.loads((fixture_dir / 'meta.json').read_text(encoding='utf-8'))
    FixtureMetaFileModel.model_validate(meta_json)
    assert 'raw_ref' not in meta_json
    assert request.url == 'https://shop.example.com/epood/cart/change/456?format=table&lang=en&include=totals'
    assert 'cookie' not in {header.lower() for header in request.headers}
    assert 'x-xsrf-token' not in {header.lower() for header in request.headers}
    response_header_names = {header.lower() for header in response.headers}
    assert 'content-type' in response_header_names
    assert 'set-cookie' not in response_header_names
    assert 'x-session-id' not in response_header_names
    assert 'x-csrf-token' not in response_header_names
    assert (fixture_dir / 'request.body').read_bytes() == b'{"delta": 2, "mode": "soft"}'
    assert (fixture_dir / 'response.body').read_bytes() == b'{"ok": true}'
    assert not (command_dir / 'raw').exists()
    assert (command_dir / 'goldens').is_dir()

    gitignore_rules = {
        line
        for line in (workspace / '.gitignore').read_text(encoding='utf-8').splitlines()
        if line and not line.startswith('#')
    }
    assert {
        '.env',
        '.autocli-playwright-storage-state.json',
        '__pycache__/',
        '*.py[cod]',
        '.pytest_cache/',
        'build/',
        'dist/',
        '*.egg-info/',
        '.eggs/',
        '.venv/',
        'venv/',
        'env/',
        'ENV/',
    } <= gitignore_rules
    assert (
        not {
            'commands/',
            'fixtures/',
            'goldens/',
            'shared/',
            'skills/',
            'command.yaml',
            'processors/',
            'tests/',
            '*.json',
            '*.yaml',
            '*.body',
        }
        & gitignore_rules
    )

    generated_test = (command_dir / 'tests' / 'test_command.py').read_text(encoding='utf-8')
    assert 'from shop_example_com.testing import run_command_contract' in generated_test
    assert 'autocli' not in generated_test

    runtime_source = (site_dir / 'runtime.py').read_text(encoding='utf-8')
    assert 'def build_app(workspace_root: Path) -> typer.Typer:' in runtime_source
    testing_source = (site_dir / 'testing.py').read_text(encoding='utf-8')
    assert 'def run_command_contract(command_dir: Path) -> None:' in testing_source
    assert agents_path.read_text(encoding='utf-8') == render_agents_md(
        site_module='shop_example_com',
        executable_name='workspace',
    )
    assert build_cli_skill_path.read_text(encoding='utf-8') == render_build_cli_skill()


def test_bootstrap_workspace_is_append_only_on_rerun(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    initial_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2'),
        ]
    )
    bootstrap_workspace(workspace, compiled_commands=initial_commands)

    existing_command_dir = workspace / 'commands' / 'get__h_shop_example_com__s_api__s_products__p_p1'
    pre_stub = existing_command_dir / 'processors' / 'pre.py'
    pre_stub.write_text('custom pre-processor\n', encoding='utf-8')

    rerun_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2'),
            make_exchange('GET', 'https://shop.example.com/api/inventory/123/full', source_id='3'),
            make_exchange('GET', 'https://shop.example.com/api/inventory/456/full', source_id='4'),
        ]
    )
    result = bootstrap_workspace(workspace, compiled_commands=rerun_commands)

    assert result['created_command_ids'] == ['get__h_shop_example_com__s_api__s_inventory__p_p1__s_full']
    assert result['skipped_command_ids'] == ['get__h_shop_example_com__s_api__s_products__p_p1']
    assert any('get__h_shop_example_com__s_api__s_products__p_p1' in warning for warning in result['warnings'])
    assert pre_stub.read_text(encoding='utf-8') == 'custom pre-processor\n'
    assert len(list((existing_command_dir / 'fixtures').iterdir())) == 1
    assert (workspace / 'AGENTS.md').exists()
    assert (workspace / 'skills' / 'build-cli' / 'SKILL.md').exists()
    assert (workspace / '.gitignore').exists()
    assert (workspace / '.env').exists()
    assert (workspace / '.env.example').exists()
    assert (
        workspace / 'commands' / 'get__h_shop_example_com__s_api__s_inventory__p_p1__s_full' / 'command.yaml'
    ).exists()
    pyproject = tomllib.loads((workspace / 'pyproject.toml').read_text(encoding='utf-8'))
    assert pyproject['project']['name'] == 'workspace'
    assert pyproject['project']['scripts'] == {'workspace': 'shop_example_com.cli:app'}


def test_bootstrap_workspace_uses_sanitized_output_dir_name_for_default_executable_name(tmp_path: Path) -> None:
    workspace = tmp_path / 'My Workspace CLI!'
    compiled_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2'),
        ]
    )

    bootstrap_workspace(workspace, compiled_commands=compiled_commands)

    pyproject = tomllib.loads((workspace / 'pyproject.toml').read_text(encoding='utf-8'))
    assert pyproject['project']['name'] == 'my-workspace-cli'
    assert pyproject['project']['scripts'] == {'my-workspace-cli': 'shop_example_com.cli:app'}
    assert pyproject['tool']['autocli']['executable_name'] == 'my-workspace-cli'


def test_bootstrap_workspace_uses_custom_executable_name_override(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    compiled_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2'),
        ]
    )

    bootstrap_workspace(workspace, compiled_commands=compiled_commands, executable_name='custom tool')

    pyproject = tomllib.loads((workspace / 'pyproject.toml').read_text(encoding='utf-8'))
    assert pyproject['project']['name'] == 'custom-tool'
    assert pyproject['project']['scripts'] == {'custom-tool': 'shop_example_com.cli:app'}
    assert pyproject['tool']['autocli']['executable_name'] == 'custom-tool'


def test_bootstrap_workspace_requires_executable_name_in_existing_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    initial_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2'),
        ]
    )
    bootstrap_workspace(workspace, compiled_commands=initial_commands)

    pyproject_path = workspace / 'pyproject.toml'
    pyproject_text = pyproject_path.read_text(encoding='utf-8')
    pyproject_path.write_text(pyproject_text.replace('executable_name = "workspace"\n', ''), encoding='utf-8')

    rerun_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='1'),
            make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='2'),
            make_exchange('GET', 'https://shop.example.com/api/inventory/123/full', source_id='3'),
            make_exchange('GET', 'https://shop.example.com/api/inventory/456/full', source_id='4'),
        ]
    )

    with pytest.raises(ValueError, match=r'missing required \[tool\.autocli\] fields: executable_name'):
        bootstrap_workspace(workspace, compiled_commands=rerun_commands)


def test_bootstrap_workspace_rejects_ambiguous_initial_host(tmp_path: Path) -> None:
    compiled_commands = build_compiled_commands(
        [
            make_exchange('GET', 'https://a.example.com/api/items/1', source_id='1'),
            make_exchange('GET', 'https://a.example.com/api/items/2', source_id='2'),
            make_exchange('GET', 'https://b.example.com/api/items/1', source_id='3'),
            make_exchange('GET', 'https://b.example.com/api/items/2', source_id='4'),
        ]
    )

    with pytest.raises(ValueError, match=r'a\.example\.com=2, b\.example\.com=2'):
        bootstrap_workspace(tmp_path / 'workspace', compiled_commands=compiled_commands)


def test_record_command_generates_workspace_from_flow(tmp_path: Path) -> None:
    capture_path = tmp_path / 'capture.flow'
    write_flow_capture(
        capture_path,
        [
            {
                'request': {
                    'method': 'GET',
                    'url': 'https://shop.example.com/api/products/123',
                    'host': 'shop.example.com',
                    'port': 443,
                    'headers': {'Accept': 'application/json'},
                    'body': b'',
                },
                'response': {
                    'status': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': b'{"id":"123"}',
                },
            },
            {
                'request': {
                    'method': 'GET',
                    'url': 'https://shop.example.com/api/products/456',
                    'host': 'shop.example.com',
                    'port': 443,
                    'headers': {'Accept': 'application/json'},
                    'body': b'',
                },
                'response': {
                    'status': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': b'{"id":"456"}',
                },
            },
        ],
    )

    runner = CliRunner()
    output_dir = tmp_path / 'generated'
    result = runner.invoke(app, ['build', str(capture_path), '--output-dir', str(output_dir)])

    assert result.exit_code == 0, result.output
    assert 'created 1 command(s), skipped 0 duplicate(s).' in result.output
    assert f'Next: uv tool install -e {output_dir.resolve()}' in result.output
    assert f'Next: use refinement skill {output_dir.resolve() / "skills" / "build-cli" / "SKILL.md"}' in result.output
    assert (output_dir / 'commands' / 'get__h_shop_example_com__s_api__s_products__p_p1' / 'command.yaml').exists()


def test_build_accepts_custom_executable_name_option(tmp_path: Path) -> None:
    capture_path = tmp_path / 'capture.flow'
    write_flow_capture(
        capture_path,
        [
            {
                'request': {
                    'method': 'GET',
                    'url': 'https://shop.example.com/api/products/123',
                    'host': 'shop.example.com',
                    'port': 443,
                    'headers': {'Accept': 'application/json'},
                    'body': b'',
                },
                'response': {
                    'status': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': b'{"id":"123"}',
                },
            },
            {
                'request': {
                    'method': 'GET',
                    'url': 'https://shop.example.com/api/products/456',
                    'host': 'shop.example.com',
                    'port': 443,
                    'headers': {'Accept': 'application/json'},
                    'body': b'',
                },
                'response': {
                    'status': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': b'{"id":"456"}',
                },
            },
        ],
    )

    runner = CliRunner()
    output_dir = tmp_path / 'generated'
    result = runner.invoke(
        app,
        ['build', str(capture_path), '--output-dir', str(output_dir), '--executable-name', 'custom tool'],
    )

    assert result.exit_code == 0, result.output
    pyproject = tomllib.loads((output_dir / 'pyproject.toml').read_text(encoding='utf-8'))
    assert pyproject['project']['scripts'] == {'custom-tool': 'shop_example_com.cli:app'}
    assert pyproject['tool']['autocli']['executable_name'] == 'custom-tool'


def test_build_rejects_legacy_command_name_option(tmp_path: Path) -> None:
    capture_path = tmp_path / 'capture.flow'
    write_flow_capture(
        capture_path,
        [
            {
                'request': {
                    'method': 'GET',
                    'url': 'https://shop.example.com/api/products/123',
                    'host': 'shop.example.com',
                    'port': 443,
                    'headers': {'Accept': 'application/json'},
                    'body': b'',
                },
                'response': {
                    'status': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': b'{"id":"123"}',
                },
            },
            {
                'request': {
                    'method': 'GET',
                    'url': 'https://shop.example.com/api/products/456',
                    'host': 'shop.example.com',
                    'port': 443,
                    'headers': {'Accept': 'application/json'},
                    'body': b'',
                },
                'response': {
                    'status': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': b'{"id":"456"}',
                },
            },
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ['build', str(capture_path), '--output-dir', str(tmp_path / 'generated'), '--command-name', 'custom-tool'],
    )

    assert result.exit_code != 0
    assert 'No such option: --command-name' in result.output


def test_build_rejects_unsupported_capture_file(tmp_path: Path) -> None:
    capture_path = tmp_path / 'capture.json'
    capture_path.write_text('{}', encoding='utf-8')

    runner = CliRunner()
    result = runner.invoke(app, ['build', str(capture_path), '--output-dir', str(tmp_path / 'generated')])

    assert result.exit_code != 0
    assert "unsupported capture file extension '.json'" in result.output
    assert 'suffixless flow capture' in result.output
