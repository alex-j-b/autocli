"""Workspace scaffolding helpers."""

from __future__ import annotations

import json
import keyword
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from mitmproxy import connection, http, io

from autocli.models import CommandFileModel, FixtureMetaFileModel, FixtureRequestFileModel, FixtureResponseFileModel
from autocli.scaffold.render import (
    derive_short_script_name,
    render_agents_md,
    render_command_module,
    render_site_package,
    render_workspace_pyproject,
)


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
    for relative_path, content in render_site_package(str(config["site_slug"])).items():
        write_text_if_missing(site_dir / relative_path, content)


def derive_cli_name(config: dict[str, Any]) -> str:
    """Derive the generated CLI command name from workspace config."""

    return derive_short_script_name(list(config["primary_hosts"]), str(config["site_slug"]))


def write_command_tree(output_dir: Path, config: dict[str, Any], command: dict[str, Any]) -> None:
    """Write one new command directory."""

    command_dir = output_dir / str(config["command_root"]) / command["id"]
    command_dir.mkdir(parents=True, exist_ok=False)
    for directory_name in ("raw", "fixtures", "goldens", "processors", "tests"):
        (command_dir / directory_name).mkdir(parents=True, exist_ok=True)

    cases = build_case_payloads(command)
    command_file = build_command_file_payload(command, cases)
    CommandFileModel.model_validate(command_file)

    for relative_path, content in render_command_module(command_file, site_module=str(config["site_module"])).items():
        write_text_file(command_dir / relative_path, content)

    for case in cases:
        write_raw_artifact(command_dir / case["raw_relpath"], case["sample"])
        fixture_dir = command_dir / case["fixture_relpath"]
        fixture_dir.mkdir(parents=True, exist_ok=True)
        write_json_file(fixture_dir / "request.json", case["request_json"])
        write_bytes_file(fixture_dir / "request.body", case["request_body"])
        write_json_file(fixture_dir / "response.json", case["response_json"])
        write_bytes_file(fixture_dir / "response.body", case["response_body"])
        write_json_file(fixture_dir / "meta.json", case["meta_json"])


def build_case_payloads(command: dict[str, Any]) -> list[dict[str, Any]]:
    """Build fixture/raw/golden payload metadata for one command."""

    samples = list(command.get("samples", []))
    case_base = case_id_base(command["cli_path"])
    cases: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        case_id = f"{case_base}_{index:03d}" if case_base else f"case_{index:03d}"
        raw_relpath = Path("raw") / f"{case_id}.flow"
        fixture_relpath = Path("fixtures") / case_id

        request_json = {
            "method": sample["request"]["method"],
            "url": sample["request"]["url"],
            "path": sample["request"]["path"],
            "query": sample["request"]["query"],
            "headers": sample["request"]["headers"],
        }
        response_json = {
            "status": sample["response"]["status"],
            "headers": sample["response"]["headers"],
        }
        meta_json = {
            "command_id": command["id"],
            "captured_at": sample["source"]["captured_at"],
            "raw_ref": raw_relpath.as_posix(),
            "flow_id": sample["source"]["capture_id"],
        }

        FixtureRequestFileModel.model_validate(request_json)
        FixtureResponseFileModel.model_validate(response_json)
        FixtureMetaFileModel.model_validate(meta_json)

        cases.append(
            {
                "id": case_id,
                "raw_relpath": raw_relpath,
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


def write_raw_artifact(path: Path, sample: dict[str, Any]) -> None:
    """Write the raw evidence artifact for one accepted sample."""

    write_bytes_file(path, build_single_flow_bytes(sample))


def build_single_flow_bytes(sample: dict[str, Any]) -> bytes:
    """Reconstruct a one-flow `.flow` artifact from a normalized sample."""

    flow = http.HTTPFlow(
        client_conn=connection.Client(peername=("127.0.0.1", 0), sockname=("127.0.0.1", 0)),
        server_conn=connection.Server(address=(sample["request"]["host"], sample["request"]["port"])),
    )
    flow.request = http.Request.make(
        sample["request"]["method"],
        sample["request"]["url"],
        content=bytes(sample["request"]["body"]),
        headers=list(flatten_mapping_items_bytes(sample["request"]["headers"])),
    )
    flow.response = http.Response.make(
        int(sample["response"]["status"]),
        content=bytes(sample["response"]["body"]),
        headers=list(flatten_mapping_items_bytes(sample["response"]["headers"])),
    )

    from io import BytesIO

    buffer = BytesIO()
    writer = io.FlowWriter(buffer)
    writer.add(flow)
    return buffer.getvalue()


def flatten_mapping_items(mapping: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten a normalized mapping that may contain repeated values."""

    items: list[tuple[str, str]] = []
    for key, value in mapping.items():
        if isinstance(value, list):
            items.extend((key, str(item)) for item in value)
        else:
            items.append((key, str(value)))
    return items


def flatten_mapping_items_bytes(mapping: dict[str, Any]) -> list[tuple[bytes, bytes]]:
    """Flatten a normalized mapping into byte header tuples for mitmproxy."""

    return [(key.encode("utf-8"), value.encode("utf-8")) for key, value in flatten_mapping_items(mapping)]


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
