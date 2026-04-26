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


def render_workspace_gitignore() -> str:
    """Render the generated workspace ``.gitignore``."""

    return """.env
.autocli-playwright-storage-state.json

__pycache__/
*.py[cod]

.pytest_cache/

build/
dist/
*.egg-info/
.eggs/

.venv/
venv/
env/
ENV/
"""


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

## What This Is

This is a generated `autocli` workspace. The parent `autocli` project generated this repository from captured HTTP traffic; this workspace is the editable product surface for turning those captures into a useful CLI.

## Repository Map

- `pyproject.toml`: package metadata, console script entry point, dependencies, and `[tool.autocli]` workspace settings.
- `{command_root}/<command>/command.yaml`: generated command metadata and request mapping.
- `{command_root}/<command>/fixtures/`: captured request/response cases used as evidence.
- `{command_root}/<command>/processors/pre.py`: request-shaping hook for live execution.
- `{command_root}/<command>/processors/post.py`: response-to-JSON hook for the CLI output contract.
- `{command_root}/<command>/goldens/`: approved post-processed output contracts.
- `shared/`: workspace-local shared code for processors or command implementations.
- `{site_module}/runtime.py`: workspace-local CLI runtime.
- `{site_module}/testing.py`: workspace-local contract test helpers.
- `skills/build-cli/SKILL.md`: iterative workflow for developing this CLI with user feedback.
- `.env`: local runtime environment. `PLAYWRIGHT_HEADERS_JSON` supply live-session headers.
- `.env.example`: example environment file.

## Governing Principles

- Captured fixtures are evidence, not a complete product specification.
- Generated command IDs, argument names, and output shapes are raw material, not final product decisions.
- Prefer pragmatic fixes in this generated workspace before changing the parent generator.
- Keep workspace-specific runtime, testing, and processor changes inside this repository.
- Goldens must reflect intentionally approved post-processed JSON, not raw transport bodies.
- Keep output schemas explicit and stable once approved.
- If the response is HTML, parse it structurally when possible.

## Working With This Workspace

- Use `skills/build-cli/SKILL.md` when the task is to improve, finish, or review the generated CLI.
- Use `processors/pre.py` only for request-shaping behavior needed by live execution.
- Use `processors/post.py` for the command's JSON output contract.
- Update goldens only when the output contract is intentionally changed.
- Stay inside this generated workspace unless there is a clear blocker that only the parent `autocli` generator can fix.

## Common Failure Modes

- Optional query/path/body args treated as required during fixture replay.
- Compressed response bodies not decoded before parsing.
- HTML or HTML-in-JSON responses handled with brittle string slicing.
- Generated `request_mapping` mismatches between args and fixture requests.
- Live-session headers not supplied correctly for authenticated requests.

## Useful Commands

- Install CLI tool: `uv tool install --editable .`
- CLI help: `{cli_name} --help` or `python -m {site_module} --help`
- Command help: `{cli_name} <command path> --help`
- Contract tests: `python -m pytest -q {command_root}/<command_id>/tests/test_command.py`
"""


def render_build_cli_skill() -> str:
    """Render the generated workspace ``build-cli`` skill."""

    return """# Build CLI Skill

Use this skill when shaping a generated `autocli` workspace into a user-approved CLI.

## Phase 1: Session And Safety

- Initialize git for the workspace if it is not already initialized.
- Make an initial commit before changing generated files when there is no existing history.
- Ensure `.env` contains `PLAYWRIGHT_HEADERS_JSON` with headers that can access the target site. To capture fresh live-session headers without printing them in the conversation:
  - In Playwright, wait for a representative authenticated request and call `await request.allHeaders()`.
  - Write `JSON.stringify({ headers })` to a temporary local storage key such as `autocli.playwrightHeadersJson`.
  - Persist the browser context to the generated workspace's absolute `.autocli-playwright-storage-state.json` path, for example `await page.context().storageState({ path: "/absolute/path/to/generated-workspace/.autocli-playwright-storage-state.json" })`.
  - Read the saved storage-state file locally, extract the temporary local storage value, and write `.env` as `PLAYWRIGHT_HEADERS_JSON=<that value>`.
  - After the storage state has been written, remove the temporary local storage key with `localStorage.removeItem("autocli.playwrightHeadersJson")`.
- If headers are missing or stale, use Playwright to visit the site and ask the user to log in when needed.
- Non-mutating requests may be used for discovery when they are useful for understanding the API or output shape.
- Ask for explicit permission before calling mutating endpoints.
- When endpoint safety is ambiguous, treat it as mutable and ask first.

## Phase 2: Inventory And Legibility

- Inspect all generated commands, fixtures, request mappings, current CLI help, and processors.
- Treat generated command IDs and paths as raw capture artifacts, not final UX.
- Group commands by user-facing concept.
- Identify duplicates, noisy captures, incomplete commands, awkward argument names, and weak output shapes.
- Rename command folders early to human-readable names so the workspace is navigable.
- Update references consistently after renames and run focused tests or validation.

## Phase 3: Product Shaping Review

For each logical command or command group:

- Explain what it appears to do in one sentence.
- Show an example invocation.
- Show or describe the expected JSON output shape.
- Proactively suggest improvements instead of waiting for the user to design the CLI.
- Offer concrete options when appropriate, such as:
  - keep as-is
  - rename
  - merge with another command
  - split into separate commands
  - remove as duplicate/noise
  - change arguments
  - change output shape
- Ask the user which direction they prefer.

Do not assume generated command names, arguments, or outputs are acceptable merely because tests pass.

## Phase 4: Refactor Toward Approved Shape

- Apply the user-approved CLI shape.
- Implement processor changes according to the approved behavior.
- Merge, split, remove, or rename commands as approved.
- Improve command metadata, help text, arguments, and output contracts.
- Update goldens only when the output contract is intentionally changed.
- Run focused tests after each substantial command change.

## Phase 5: Acceptance Review

- Review the actual refactored commands one by one.
- Show command help and representative output.
- Ask whether each command is accepted or needs another change.
- Continue review/refactor rounds until the user accepts the CLI.

## Done Criteria

- `.env` auth/session setup is working or clearly documented.
- Command folders are human-readable.
- Commands are grouped around user concepts rather than capture artifacts.
- Duplicate/noisy commands have been handled.
- Arguments and output shapes have been intentionally reviewed.
- Goldens reflect approved output contracts.
- Contract tests pass.
- The user has accepted the final command set.
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
