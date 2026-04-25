"""Source rendering helpers for generated workspaces."""

from __future__ import annotations

import re
from typing import Any

import yaml

from autocli.runtime.templates import render_cli_module, render_package_init, render_package_main, render_runtime_module
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

WORKSPACE_ENV_PLACEHOLDER = 'PLAYWRIGHT_HEADERS_JSON={"headers":{}}\n'


def render_workspace_pyproject(
    *,
    site_slug: str,
    site_module: str,
    primary_hosts: list[str],
) -> str:
    """Render the generated workspace ``pyproject.toml``."""

    dependencies = ",\n".join(f'  "{dependency}"' for dependency in WORKSPACE_RUNTIME_DEPENDENCIES)
    hosts = ", ".join(f'"{host}"' for host in primary_hosts)
    cli_name = derive_short_script_name(primary_hosts, site_slug)
    return f"""[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{cli_name}"
version = "0.1.0"
description = "Generated CLI workspace for {cli_name}"
requires-python = ">=3.12"
dependencies = [
{dependencies}
]

[project.scripts]
{cli_name} = "{site_module}.cli:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["commands*", "shared*", "{site_module}*"]

[tool.autocli]
schema_version = 1
site_slug = "{site_slug}"
site_module = "{site_module}"
primary_hosts = [{hosts}]
command_root = "commands"
shared_package = "shared"
"""


def render_agents_md(*, site_module: str, cli_name: str, command_root: str = "commands") -> str:
    """Render the generated workspace ``AGENTS.md`` guidance."""

    return f"""# AGENTS.md

## Goal
- Make generated command(s) functional end to end inside this workspace.
- Prefer pragmatic fixes in this generated workspace before changing the generator project.

## Start Here
1. Inspect `{command_root}/` and each generated command directory.
2. Read `command.yaml`, fixtures, goldens, processor stubs, and workspace-local runtime/testing helpers.
3. Pick one command and carry it end to end first.

## Expected Workflow
1. Infer a stable JSON output shape from the fixture cases.
2. Check workspace-local runtime/testing helpers for replay issues before editing processors.
3. Fix local helper/runtime bugs when they block fixture replay or live execution.
4. Implement `processors/pre.py` only as needed to construct the live request.
5. Implement `processors/post.py` to return clean JSON-serializable output.
6. Create approved goldens for every declared fixture of the chosen command.
7. Run the generated contract test and iterate until it passes. A passing run marks the command complete and makes it available in the CLI.
8. Run the generated CLI locally and verify it returns the expected JSON.

## Common Failure Modes
- Optional query/path/body args treated as required during fixture replay.
- Compressed response bodies not decoded before parsing.
- HTML or HTML-in-JSON responses handled with brittle string slicing.
- Generated `request_mapping` mismatches between args and fixture requests.
- Live-session headers not supplied correctly for authenticated requests.

## Constraints
- Stay inside this generated workspace unless there is a clear blocker that only the generator can fix.
- Keep output schemas explicit and stable.
- Goldens must reflect final post-processed JSON, not raw transport bodies.
- If the response is HTML, parse it structurally when possible.

## Useful Commands
- Install CLI tool: `uv tool install --editable .`
- CLI help: `{cli_name} --help` or `python -m {site_module} --help`
- Command help: `{cli_name} <command path> --help`
- Contract tests: `python -m pytest -q {command_root}/<command_id>/tests/test_command.py`
- Live authenticated runs can use `PLAYWRIGHT_HEADERS_JSON={{...}}` in `.env`

## Deliverables
- Functional processor implementations.
- Any required workspace-local runtime/testing fixes.
- Approved goldens for the completed command.
- Passing generated tests for that command.
- A short summary of the final JSON output contract, assumptions, fixes, and remaining risks.
"""


def render_workspace_env() -> str:
    """Render the generated workspace ``.env`` placeholder."""

    return WORKSPACE_ENV_PLACEHOLDER


def render_workspace_env_example() -> str:
    """Render the generated workspace ``.env.example`` placeholder."""

    return WORKSPACE_ENV_PLACEHOLDER


def derive_short_script_name(primary_hosts: list[str], site_slug: str) -> str:
    """Derive a short console-script alias from the primary host."""

    host = primary_hosts[0] if primary_hosts else site_slug
    labels = [label for label in host.lower().split(".") if label]
    if labels and labels[0] in {"www", "m", "app"}:
        labels = labels[1:]
    if len(labels) >= 2:
        candidate = labels[-2]
    elif labels:
        candidate = labels[0]
    else:
        candidate = site_slug
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate).strip("-")
    return candidate or site_slug


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
    return f'''"""Generated {phase_label} stub."""

from __future__ import annotations


def run(context: dict[str, object]) -> dict[str, object]:
    _ = context
    raise NotImplementedError("Implement the {phase_label}.")
'''
