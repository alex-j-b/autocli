"""Source rendering helpers for generated workspaces."""

from __future__ import annotations

import re
from typing import Any

import yaml

from autocli.templating import render_template

WORKSPACE_RUNTIME_DEPENDENCIES = [
    'httpx>=0.27,<1',
    'keyring>=25,<26',
    'msgpack>=1,<2',
    'pydantic>=2.8,<3',
    'PyYAML>=6,<7',
    'rich>=13.7,<14',
    'typer>=0.16,<1',
]

WORKSPACE_DEV_DEPENDENCIES = [
    'pytest>=8.3,<9',
]

SITE_PACKAGE_TEMPLATE_PATHS = {
    '__init__.py': 'runtime/package_init.py.j2',
    '__main__.py': 'runtime/package_main.py.j2',
    'cli.py': 'runtime/cli.py.j2',
    'testing.py': 'testing/testing.py.j2',
}


def render_workspace_gitignore() -> str:
    """Render the generated workspace ``.gitignore``."""

    return render_template('scaffold/workspace_gitignore.j2')


def render_workspace_pyproject(
    *,
    executable_name: str,
    site_slug: str,
    site_module: str,
    primary_hosts: list[str],
) -> str:
    """Render the generated workspace ``pyproject.toml``."""

    return render_template(
        'scaffold/workspace_pyproject.toml.j2',
        executable_name=executable_name,
        site_slug=site_slug,
        site_module=site_module,
        runtime_dependencies_block=',\n'.join(f'  "{dependency}"' for dependency in WORKSPACE_RUNTIME_DEPENDENCIES),
        dev_dependencies_block=',\n'.join(f'  "{dependency}"' for dependency in WORKSPACE_DEV_DEPENDENCIES),
        hosts_inline=', '.join(f'"{host}"' for host in primary_hosts),
    )


def render_agents_md(*, site_module: str, executable_name: str, command_root: str = 'commands') -> str:
    """Render the generated workspace ``AGENTS.md`` guidance."""

    return render_template(
        'scaffold/agents.md.j2',
        site_module=site_module,
        executable_name=executable_name,
        command_root=command_root,
    )


def render_build_cli_skill() -> str:
    """Render the generated workspace ``build-cli`` skill."""

    return render_template('scaffold/build_cli_skill.md.j2')


def render_authenticate_skill() -> str:
    """Render the generated workspace ``authenticate`` skill."""

    return render_template('scaffold/authenticate_skill.md.j2')


def normalize_executable_name(raw_name: str, *, fallback: str | None = None) -> str:
    """Normalize an installed executable name into a console-script-safe token."""

    normalized = re.sub(r'[^a-z0-9]+', '-', raw_name.lower()).strip('-')
    if normalized:
        return normalized
    if fallback is None:
        raise ValueError('command name must contain at least one ASCII letter or digit')
    fallback_name = re.sub(r'[^a-z0-9]+', '-', fallback.lower()).strip('-')
    return fallback_name or 'generated-cli'


def render_site_package(site_slug: str, *, keyring_service: str) -> dict[str, str]:
    """Render the generated site package modules."""

    return {
        relative_path: render_template(template_path)
        for relative_path, template_path in SITE_PACKAGE_TEMPLATE_PATHS.items()
    } | {
        'runtime.py': render_template(
            'runtime/runtime.py.j2',
            site_slug=site_slug,
            keyring_service=keyring_service,
        ),
    }


def render_command_module(command_spec: dict[str, Any], *, site_module: str) -> dict[str, str]:
    """Render text files for one generated command module."""

    return {
        'command.yaml': render_command_yaml(command_spec),
        'processors/__init__.py': '',
        'processors/pre.py': render_processor_stub('pre'),
        'processors/post.py': render_processor_stub('post'),
        'tests/__init__.py': '',
        'tests/test_command.py': render_template('testing/command_test.py.j2', site_module=site_module),
    }


def render_command_yaml(command_spec: dict[str, Any]) -> str:
    """Render the command manifest YAML."""

    return yaml.safe_dump(command_spec, sort_keys=False, allow_unicode=False)


def render_processor_stub(phase: str) -> str:
    """Render a generated processor stub."""

    phase_label = 'pre-processor' if phase == 'pre' else 'post-processor'
    return render_template('scaffold/processor_stub.py.j2', phase_label=phase_label)
