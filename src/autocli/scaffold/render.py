"""Source rendering helpers for generated workspaces."""

from __future__ import annotations

import re
from typing import Any

import yaml

from autocli.runtime.templates import render_cli_module, render_package_init, render_package_main, render_runtime_module
from autocli.templating import render_template
from autocli.testing.templates import render_command_test, render_testing_module

WORKSPACE_RUNTIME_DEPENDENCIES = [
    "httpx>=0.27,<1",
    "msgpack>=1,<2",
    "pydantic>=2.8,<3",
    "python-dotenv>=1,<2",
    "PyYAML>=6,<7",
    "pytest>=8.3,<9",
    "rich>=13.7,<14",
    "typer>=0.16,<1",
]


def render_workspace_gitignore() -> str:
    """Render the generated workspace ``.gitignore``."""

    return render_template("scaffold/workspace_gitignore.j2")


def render_workspace_pyproject(
    *,
    cli_name: str,
    site_slug: str,
    site_module: str,
    primary_hosts: list[str],
) -> str:
    """Render the generated workspace ``pyproject.toml``."""

    return render_template(
        "scaffold/workspace_pyproject.toml.j2",
        cli_name=cli_name,
        site_slug=site_slug,
        site_module=site_module,
        dependencies_block=",\n".join(f'  "{dependency}"' for dependency in WORKSPACE_RUNTIME_DEPENDENCIES),
        hosts_inline=", ".join(f'"{host}"' for host in primary_hosts),
    )


def render_agents_md(*, site_module: str, cli_name: str, command_root: str = "commands") -> str:
    """Render the generated workspace ``AGENTS.md`` guidance."""

    return render_template(
        "scaffold/agents.md.j2",
        site_module=site_module,
        cli_name=cli_name,
        command_root=command_root,
    )


def render_build_cli_skill() -> str:
    """Render the generated workspace ``build-cli`` skill."""

    return render_template("scaffold/build_cli_skill.md.j2")


def render_workspace_env() -> str:
    """Render the generated workspace ``.env`` placeholder."""

    return render_template("scaffold/workspace_env.j2")


def render_workspace_env_example() -> str:
    """Render the generated workspace ``.env.example`` placeholder."""

    return render_template("scaffold/workspace_env.j2")


def normalize_cli_name(raw_name: str, *, fallback: str) -> str:
    """Normalize a workspace folder name into a console-script-safe CLI name."""

    normalized = re.sub(r"[^a-z0-9]+", "-", raw_name.lower()).strip("-")
    if normalized:
        return normalized
    fallback_name = re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-")
    return fallback_name or "generated-cli"


def render_site_package(site_slug: str) -> dict[str, str]:
    """Render the generated site package modules."""

    return {
        "__init__.py": render_package_init(),
        "__main__.py": render_package_main(),
        "cli.py": render_cli_module(),
        "runtime.py": render_runtime_module(site_slug),
        "testing.py": render_testing_module(),
    }


def render_command_module(command_spec: dict[str, Any], *, site_module: str) -> dict[str, str]:
    """Render text files for one generated command module."""

    return {
        "command.yaml": render_command_yaml(command_spec),
        "processors/__init__.py": "",
        "processors/pre.py": render_processor_stub("pre"),
        "processors/post.py": render_processor_stub("post"),
        "tests/__init__.py": "",
        "tests/test_command.py": render_command_test(site_module),
    }


def render_command_yaml(command_spec: dict[str, Any]) -> str:
    """Render the command manifest YAML."""

    return yaml.safe_dump(command_spec, sort_keys=False, allow_unicode=False)


def render_processor_stub(phase: str) -> str:
    """Render a generated processor stub."""

    phase_label = "pre-processor" if phase == "pre" else "post-processor"
    return render_template("scaffold/processor_stub.py.j2", phase_label=phase_label)
