"""Workspace scaffolding helpers."""

from __future__ import annotations

import json
import keyword
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from autocli.models import CommandFileModel, FixtureMetaFileModel, FixtureRequestFileModel, FixtureResponseFileModel
from autocli.scaffold.render import (
    derive_short_script_name,
    render_agents_md,
    render_build_cli_skill,
    render_command_module,
    render_site_package,
    render_workspace_env,
    render_workspace_env_example,
    render_workspace_pyproject,
)

SESSION_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "csrf-token",
    "x-csrf-token",
    "x-requested-with",
    "x-xsrf-token",
    "xsrf-token",
}
SESSION_SENSITIVE_HEADER_SUBSTRINGS = ("auth", "csrf", "session", "token")


def bootstrap_workspace(output_dir: Path, *, compiled_commands: list[dict[str, Any]]) -> dict[str, Any]:
    """Bootstrap or extend a generated workspace."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_workspace_config(output_dir)
    if config is None:
        ensure_bootstrap_target_is_clean(output_dir)
        config = derive_workspace_config(compiled_commands)
        initialize_workspace(output_dir, config)
    else:
        ensure_workspace_scaffold(output_dir, config)

    created_command_ids: list[str] = []
    skipped_command_ids: list[str] = []
    warnings: list[str] = []

    command_root = output_dir / str(config["command_root"])
    for command in sorted(compiled_commands, key=lambda item: item["id"]):
        command_dir = command_root / command["id"]
        if command_dir.exists():
            skipped_command_ids.append(command["id"])
            warnings.append(f"Skipped existing command tree {command['id']} at {command_dir}")
            continue
        write_command_tree(output_dir, config, command)
        created_command_ids.append(command["id"])

    return {
        "workspace_root": str(output_dir),
        "refinement_skill_path": str(output_dir / "skills" / "build-cli" / "SKILL.md"),
        "site_slug": str(config["site_slug"]),
        "site_module": str(config["site_module"]),
        "created_command_ids": created_command_ids,
        "skipped_command_ids": skipped_command_ids,
        "warnings": warnings,
    }


def load_workspace_config(output_dir: Path) -> dict[str, Any] | None:
    """Load an existing generated workspace configuration."""

    pyproject_path = output_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    tool_config = data.get("tool", {}).get("autocli")
    if tool_config is None:
        raise ValueError(f"{pyproject_path} already exists but is not an autocli workspace")

    required_fields = {"schema_version", "site_slug", "site_module", "primary_hosts", "command_root", "shared_package"}
    missing = sorted(required_fields - set(tool_config))
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{pyproject_path} is missing required [tool.autocli] fields: {missing_text}")
    return dict(tool_config)


def ensure_bootstrap_target_is_clean(output_dir: Path) -> None:
    """Require an empty directory for first-time bootstrap."""

    existing_entries = sorted(path.name for path in output_dir.iterdir())
    if existing_entries:
        existing_text = ", ".join(existing_entries)
        raise ValueError(
            f"{output_dir} is not empty. Bootstrap requires an empty directory or an existing autocli workspace. "
            f"Found: {existing_text}"
        )


def derive_workspace_config(compiled_commands: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive initial workspace metadata from compiled commands."""

    host_counts: Counter[str] = Counter()
    for command in compiled_commands:
        for sample in command.get("samples", []):
            host_counts[str(sample["request"]["host"])] += 1

    if not host_counts:
        raise ValueError("Cannot bootstrap a workspace without compiled commands")

    top_count = max(host_counts.values())
    dominant_hosts = sorted(host for host, count in host_counts.items() if count == top_count)
    if len(dominant_hosts) != 1:
        counts_text = ", ".join(f"{host}={host_counts[host]}" for host in sorted(host_counts))
        raise ValueError(f"Bootstrap requires a single dominant host. Candidates: {counts_text}")

    dominant_host = dominant_hosts[0]
    primary_hosts = [host for host, _ in sorted(host_counts.items(), key=lambda item: (-item[1], item[0]))]
    site_slug = host_to_site_slug(dominant_host)
    site_module = site_slug_to_module_name(site_slug)

    return {
        "schema_version": 1,
        "site_slug": site_slug,
        "site_module": site_module,
        "primary_hosts": primary_hosts,
        "command_root": "commands",
        "shared_package": "shared",
    }


def host_to_site_slug(host: str) -> str:
    """Convert a canonical host into the initial site slug."""

    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
    return slug or "generated-site"


def site_slug_to_module_name(site_slug: str) -> str:
    """Convert a site slug into a valid Python package name."""

    module_name = site_slug.replace("-", "_")
    module_name = re.sub(r"[^a-zA-Z0-9_]+", "_", module_name).strip("_")
    if not module_name:
        module_name = "generated_site"
    if not module_name.isidentifier() or keyword.iskeyword(module_name):
        module_name = f"site_{module_name}"
    if not module_name.isidentifier() or keyword.iskeyword(module_name):
        module_name = "site_generated"
    return module_name


def initialize_workspace(output_dir: Path, config: dict[str, Any]) -> None:
    """Create the workspace root structure on first bootstrap."""

    pyproject_path = output_dir / "pyproject.toml"
    write_text_file(
        pyproject_path,
        render_workspace_pyproject(
            site_slug=str(config["site_slug"]),
            site_module=str(config["site_module"]),
            primary_hosts=list(config["primary_hosts"]),
        ),
    )
    ensure_workspace_scaffold(output_dir, config)


def ensure_workspace_scaffold(output_dir: Path, config: dict[str, Any]) -> None:
    """Ensure the shared/site-package bootstrap files exist."""

    shared_dir = output_dir / str(config["shared_package"])
    commands_dir = output_dir / str(config["command_root"])
    site_dir = output_dir / str(config["site_module"])
    build_cli_skill_path = output_dir / "skills" / "build-cli" / "SKILL.md"

    shared_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)

    write_text_if_missing(shared_dir / "__init__.py", "")
    write_text_if_missing(commands_dir / "__init__.py", "")
    write_text_if_missing(
        output_dir / "AGENTS.md",
        render_agents_md(
            site_module=str(config["site_module"]),
            cli_name=derive_cli_name(config),
            command_root=str(config["command_root"]),
        ),
    )
    write_text_if_missing(build_cli_skill_path, render_build_cli_skill())
    write_text_if_missing(output_dir / ".env", render_workspace_env())
    write_text_if_missing(output_dir / ".env.example", render_workspace_env_example())
    for relative_path, content in render_site_package(str(config["site_slug"])).items():
        write_text_if_missing(site_dir / relative_path, content)


def derive_cli_name(config: dict[str, Any]) -> str:
    """Derive the generated CLI command name from workspace config."""

    return derive_short_script_name(list(config["primary_hosts"]), str(config["site_slug"]))


def write_command_tree(output_dir: Path, config: dict[str, Any], command: dict[str, Any]) -> None:
    """Write one new command directory."""

    command_dir = output_dir / str(config["command_root"]) / command["id"]
    command_dir.mkdir(parents=True, exist_ok=False)
    for directory_name in ("fixtures", "goldens", "processors", "tests"):
        (command_dir / directory_name).mkdir(parents=True, exist_ok=True)

    cases = build_case_payloads(command)
    command_file = build_command_file_payload(command, cases)
    CommandFileModel.model_validate(command_file)

    for relative_path, content in render_command_module(command_file, site_module=str(config["site_module"])).items():
        write_text_file(command_dir / relative_path, content)

    for case in cases:
        fixture_dir = command_dir / case["fixture_relpath"]
        fixture_dir.mkdir(parents=True, exist_ok=True)
        write_json_file(fixture_dir / "request.json", case["request_json"])
        write_bytes_file(fixture_dir / "request.body", case["request_body"])
        write_json_file(fixture_dir / "response.json", case["response_json"])
        write_bytes_file(fixture_dir / "response.body", case["response_body"])
        write_json_file(fixture_dir / "meta.json", case["meta_json"])


def build_case_payloads(command: dict[str, Any]) -> list[dict[str, Any]]:
    """Build fixture/golden payload metadata for one command."""

    samples = select_fixture_samples(list(command.get("samples", [])))
    case_base = case_id_base(command["cli_path"])
    cases: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        case_id = f"{case_base}_{index:03d}" if case_base else f"case_{index:03d}"
        fixture_relpath = Path("fixtures") / case_id

        request_json = {
            "method": sample["request"]["method"],
            "url": sample["request"]["url"],
            "path": sample["request"]["path"],
            "query": sample["request"]["query"],
            "headers": strip_session_sensitive_headers(sample["request"]["headers"]),
        }
        response_json = {
            "status": sample["response"]["status"],
            "headers": sample["response"]["headers"],
        }
        meta_json = {
            "command_id": command["id"],
            "captured_at": sample["source"]["captured_at"],
        }

        FixtureRequestFileModel.model_validate(request_json)
        FixtureResponseFileModel.model_validate(response_json)
        FixtureMetaFileModel.model_validate(meta_json)

        cases.append(
            {
                "id": case_id,
                "fixture_relpath": fixture_relpath,
                "golden_relpath": Path("goldens") / f"{case_id}.json",
                "request_json": request_json,
                "request_body": bytes(sample["request"]["body"]),
                "response_json": response_json,
                "response_body": bytes(sample["response"]["body"]),
                "meta_json": meta_json,
                "sample": sample,
            }
        )
    return cases


def select_fixture_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the single fixture sample with the longest URL, preserving capture order for ties."""

    if not samples:
        return []
    return [max(samples, key=lambda sample: len(str(sample["request"]["url"])))]


def build_command_file_payload(command: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the full ``command.yaml`` payload."""

    command_payload: dict[str, Any] = {
        "version": 1,
        "command": {
            "id": command["id"],
            "cli_path": list(command["cli_path"]),
            "summary": command["summary"],
            "complete": False,
            "request": command["request"],
            "processors": {
                "pre": "processors.pre",
                "post": "processors.post",
            },
            "fixtures": [{"id": case["id"], "path": case["fixture_relpath"].as_posix()} for case in cases],
            "goldens": [{"id": case["id"], "path": case["golden_relpath"].as_posix()} for case in cases],
        },
    }
    if command.get("arguments"):
        command_payload["command"]["arguments"] = command["arguments"]
    if command.get("request_mapping"):
        command_payload["command"]["request_mapping"] = command["request_mapping"]
    if command.get("description"):
        command_payload["command"]["description"] = command["description"]
    return command_payload


def case_id_base(cli_path: list[str]) -> str:
    """Build the readable fixture id prefix from the cli path."""

    tokens = [segment.replace("-", "_") for segment in cli_path if segment]
    return "_".join(tokens)


def strip_session_sensitive_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Remove headers that must be supplied through PLAYWRIGHT_HEADERS_JSON at runtime."""

    return {name: value for name, value in headers.items() if not is_session_sensitive_header(name)}


def is_session_sensitive_header(header_name: str) -> bool:
    """Return whether a header should never be persisted in generated fixtures."""

    normalized = header_name.lower()
    if normalized in SESSION_SENSITIVE_HEADER_NAMES:
        return True
    if normalized.startswith("sec-"):
        return True
    return any(token in normalized for token in SESSION_SENSITIVE_HEADER_SUBSTRINGS)


def write_text_if_missing(path: Path, content: str) -> None:
    """Write a text file only when it does not already exist."""

    if not path.exists():
        write_text_file(path, content)


def write_text_file(path: Path, content: str) -> None:
    """Write a text file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json_file(path: Path, payload: Any) -> None:
    """Write deterministic JSON with a trailing newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_bytes_file(path: Path, payload: bytes) -> None:
    """Write raw bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
