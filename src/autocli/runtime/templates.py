"""Generated runtime template renderers."""

from __future__ import annotations

from textwrap import dedent


def render_package_init() -> str:
    """Render the generated site package ``__init__`` module."""

    return '"""Generated site CLI package."""\n\n__all__ = ["__version__"]\n\n__version__ = "0.1.0"\n'


def render_package_main() -> str:
    """Render the generated site package ``__main__`` module."""

    return '"""Module entrypoint for the generated site CLI."""\n\nfrom .cli import app\n\n\nif __name__ == "__main__":\n    app()\n'


def render_cli_module() -> str:
    """Render the generated site package ``cli.py`` module."""

    return dedent(
        """
        \"\"\"Generated CLI entrypoint.\"\"\"

        from __future__ import annotations

        from pathlib import Path

        from .runtime import build_app

        WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
        app = build_app(WORKSPACE_ROOT)
        """
    )


def render_runtime_module(site_slug: str) -> str:
    """Render the generated site package runtime helpers."""

    return dedent(
        """
        \"\"\"Generated runtime helpers for the __SITE_SLUG__ workspace.\"\"\"

        from __future__ import annotations

        import copy
        import gzip
        import importlib
        import inspect
        import json
        import keyword
        import os
        import re
        import sys
        import tomllib
        import urllib.parse
        import zlib
        from collections import defaultdict
        from pathlib import Path, PurePosixPath
        from typing import Any, Literal

        import httpx
        import msgpack
        import typer
        import yaml
        from dotenv import load_dotenv
        from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

        PLAYWRIGHT_HEADERS_JSON_ENV = "PLAYWRIGHT_HEADERS_JSON"
        TEST_MODE_ENV = "AUTOCLI_TEST_MODE"
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

        type JsonScalar = str | int | float | bool | None
        type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
        type HeaderValue = str | list[str]
        type QueryValue = str | list[str]
        type RuntimeBodyValue = JsonValue | bytes

        APPROVED_GOLDEN_VALUE_ADAPTER = TypeAdapter(JsonValue)

        _COMMAND_ID_RE = re.compile(r"^[a-z0-9_]+(?:__[a-z0-9_]+)*$")
        _CLI_PATH_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        _CLI_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        _CASE_ID_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
        _MODULE_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*$")
        _REQUEST_MAPPING_SOURCE_RE = re.compile(r"^args\\.([A-Za-z_][A-Za-z0-9_]*)$")
        _REQUEST_MAPPING_TARGET_RE = re.compile(
            r"^(?:"
            r"request\\.(?:params|query|headers|cookies)\\.[A-Za-z0-9_-]+"
            r"|request\\.body(?:\\.[A-Za-z0-9_-]+)*"
            r")$"
        )
        _SKIP_REQUEST_MAPPING = object()


        def validate_approved_golden(value: Any) -> JsonValue:
            \"\"\"Validate an approved golden as a plain JSON value.\"\"\"

            return APPROVED_GOLDEN_VALUE_ADAPTER.validate_python(value)


        def _validate_command_id(value: str) -> str:
            if not _COMMAND_ID_RE.fullmatch(value):
                raise ValueError("command ids must be lowercase snake-style tokens separated by double underscores")
            return value


        def _validate_cli_segment(value: str) -> str:
            if not _CLI_PATH_SEGMENT_RE.fullmatch(value):
                raise ValueError("cli_path segments must be lowercase kebab-case tokens")
            return value


        def _validate_cli_name(value: str) -> str:
            if not _CLI_NAME_RE.fullmatch(value):
                raise ValueError("argument names must be lowercase kebab-case tokens")
            return value


        def _validate_python_name(value: str) -> str:
            if not value.isidentifier() or keyword.iskeyword(value):
                raise ValueError("python_name must be a valid Python identifier")
            return value


        def _validate_case_id(value: str) -> str:
            if not _CASE_ID_RE.fullmatch(value):
                raise ValueError("fixture and golden ids must be lowercase readable tokens")
            return value


        def _validate_relative_path(value: str, *, root: str, suffix: str | None = None) -> str:
            path = PurePosixPath(value)
            if path.is_absolute():
                raise ValueError("paths must be relative")
            if any(part == ".." for part in path.parts):
                raise ValueError("paths must stay within the command directory")
            if not path.parts or path.parts[0] != root:
                raise ValueError(f"paths must live under {root}/")
            if suffix and not value.endswith(suffix):
                raise ValueError(f"paths must end with {suffix}")
            return value


        def _validate_module_ref(value: str) -> str:
            if not _MODULE_REF_RE.fullmatch(value):
                raise ValueError("processor refs must be dotted Python module paths")
            if not value.startswith("processors."):
                raise ValueError("processor refs must live under the processors package")
            return value


        def _matches_argument_type(value: JsonScalar, argument_type: str) -> bool:
            if argument_type == "string":
                return isinstance(value, str)
            if argument_type == "integer":
                return isinstance(value, int) and not isinstance(value, bool)
            if argument_type == "number":
                return isinstance(value, (int, float)) and not isinstance(value, bool)
            if argument_type == "boolean":
                return isinstance(value, bool)
            return False


        def _ensure_unique(items: list[BaseModel], field_name: str, label: str) -> None:
            seen: set[str] = set()
            duplicates: set[str] = set()
            for item in items:
                value = getattr(item, field_name)
                if value in seen:
                    duplicates.add(value)
                seen.add(value)
            if duplicates:
                duplicates_text = ", ".join(sorted(duplicates))
                raise ValueError(f"{label} must be unique within a command: {duplicates_text}")


        def _validate_request_mapping_target(target: str) -> tuple[str, ...]:
            if not _REQUEST_MAPPING_TARGET_RE.fullmatch(target):
                raise ValueError(
                    "request_mapping targets must write to request.params, request.query, "
                    "request.headers, request.cookies, request.body, or request.body.<path>"
                )
            return tuple(target.split("."))


        def _validate_request_mapping_value(value: JsonValue, defined_args: set[str]) -> None:
            if not isinstance(value, str):
                return
            if not value.startswith("args"):
                return
            match = _REQUEST_MAPPING_SOURCE_RE.fullmatch(value)
            if not match:
                raise ValueError("request_mapping sources may only reference args.<python_name>")
            python_name = match.group(1)
            if python_name not in defined_args:
                raise ValueError(f"request_mapping references undefined argument {python_name!r}")


        def _validate_no_body_mapping_conflicts(targets: list[tuple[str, ...]]) -> None:
            body_targets = sorted(
                (target for target in targets if len(target) >= 2 and target[0] == "request" and target[1] == "body"),
                key=len,
            )
            for index, left in enumerate(body_targets):
                for right in body_targets[index + 1 :]:
                    if right[: len(left)] == left:
                        raise ValueError("request_mapping body targets must not overlap")


        class PathShapeSegmentModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            kind: Literal["literal", "parameter"]
            value: str = Field(min_length=1)

            @model_validator(mode="after")
            def validate_segment(self) -> "PathShapeSegmentModel":
                if self.kind == "literal":
                    if "/" in self.value:
                        raise ValueError("literal path-shape values must not contain slashes")
                    return self
                _validate_python_name(self.value)
                return self


        class CommandArgumentModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            name: str = Field(min_length=1)
            python_name: str = Field(min_length=1)
            kind: Literal["option", "argument"]
            type: Literal["string", "integer", "number", "boolean"]
            required: bool
            help: str | None = None
            default: JsonScalar = None
            choices: list[JsonScalar] | None = None

            @field_validator("name")
            @classmethod
            def validate_name(cls, value: str) -> str:
                return _validate_cli_name(value)

            @field_validator("python_name")
            @classmethod
            def validate_python_name(cls, value: str) -> str:
                return _validate_python_name(value)

            @model_validator(mode="after")
            def validate_argument(self) -> "CommandArgumentModel":
                if self.required and self.default is not None:
                    raise ValueError("required and default must not be combined")
                if self.type == "boolean" and self.kind != "option":
                    raise ValueError("boolean arguments must be options")
                if self.default is not None and not _matches_argument_type(self.default, self.type):
                    raise ValueError("default must match the declared type")
                if self.choices:
                    for choice in self.choices:
                        if not _matches_argument_type(choice, self.type):
                            raise ValueError("choices must match the declared type")
                return self


        class ProcessorRefsModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            pre: str
            post: str

            @field_validator("pre", "post")
            @classmethod
            def validate_ref(cls, value: str) -> str:
                return _validate_module_ref(value)


        class FixtureRefModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            id: str
            path: str

            @field_validator("id")
            @classmethod
            def validate_id(cls, value: str) -> str:
                return _validate_case_id(value)

            @field_validator("path")
            @classmethod
            def validate_path(cls, value: str) -> str:
                return _validate_relative_path(value, root="fixtures")


        class GoldenRefModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            id: str
            path: str

            @field_validator("id")
            @classmethod
            def validate_id(cls, value: str) -> str:
                return _validate_case_id(value)

            @field_validator("path")
            @classmethod
            def validate_path(cls, value: str) -> str:
                return _validate_relative_path(value, root="goldens", suffix=".json")


        class CommandRequestModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            method: str = Field(min_length=1)
            url_template: str = Field(min_length=1)
            path_template: str = Field(min_length=1)
            path_shape: list[PathShapeSegmentModel]
            params: dict[str, JsonValue] = Field(default_factory=dict)
            query: dict[str, QueryValue] = Field(default_factory=dict)
            headers: dict[str, HeaderValue] = Field(default_factory=dict)
            cookies: dict[str, str] = Field(default_factory=dict)
            body: RuntimeBodyValue | None = None
            query_schema: dict[str, JsonValue] | None = None
            headers_schema: dict[str, JsonValue] | None = None
            body_schema: dict[str, JsonValue] | None = None

            @field_validator("method")
            @classmethod
            def validate_method(cls, value: str) -> str:
                if value != value.upper():
                    raise ValueError("request methods must be uppercase")
                return value

            @field_validator("path_template")
            @classmethod
            def validate_path_template(cls, value: str) -> str:
                if not value.startswith("/"):
                    raise ValueError("path_template must start with '/'")
                return value


        class CommandSpecModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            id: str
            cli_path: list[str] = Field(min_length=1)
            summary: str = Field(min_length=1)
            complete: bool = True
            request: CommandRequestModel
            processors: ProcessorRefsModel
            fixtures: list[FixtureRefModel] = Field(min_length=1)
            goldens: list[GoldenRefModel] = Field(min_length=1)
            description: str | None = None
            arguments: list[CommandArgumentModel] = Field(default_factory=list)
            request_mapping: dict[str, JsonValue] = Field(default_factory=dict)

            @field_validator("id")
            @classmethod
            def validate_id(cls, value: str) -> str:
                return _validate_command_id(value)

            @field_validator("cli_path")
            @classmethod
            def validate_cli_path(cls, value: list[str]) -> list[str]:
                return [_validate_cli_segment(segment) for segment in value]

            @model_validator(mode="after")
            def validate_command(self) -> "CommandSpecModel":
                _ensure_unique(self.arguments, "name", "argument names")
                _ensure_unique(self.arguments, "python_name", "argument python_names")
                _ensure_unique(self.fixtures, "id", "fixture ids")
                _ensure_unique(self.goldens, "id", "golden ids")

                fixture_ids = {fixture.id for fixture in self.fixtures}
                golden_ids = {golden.id for golden in self.goldens}
                if golden_ids != fixture_ids:
                    raise ValueError("fixtures and goldens must match exactly by id")

                defined_args = {argument.python_name for argument in self.arguments}
                targets: list[tuple[str, ...]] = []
                for target, source in self.request_mapping.items():
                    targets.append(_validate_request_mapping_target(target))
                    _validate_request_mapping_value(source, defined_args)
                _validate_no_body_mapping_conflicts(targets)
                return self


        class CommandFileModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            version: Literal[1]
            command: CommandSpecModel


        class FixtureRequestFileModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            method: str = Field(min_length=1)
            url: str = Field(min_length=1)
            path: str = Field(min_length=1)
            query: dict[str, QueryValue]
            headers: dict[str, HeaderValue]

            @field_validator("method")
            @classmethod
            def validate_method(cls, value: str) -> str:
                if value != value.upper():
                    raise ValueError("request methods must be uppercase")
                return value

            @field_validator("path")
            @classmethod
            def validate_path(cls, value: str) -> str:
                if not value.startswith("/"):
                    raise ValueError("paths must start with '/'")
                return value


        class FixtureResponseFileModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            status: int
            headers: dict[str, HeaderValue]

            @field_validator("status")
            @classmethod
            def validate_status(cls, value: int) -> int:
                if value < 100 or value > 599:
                    raise ValueError("status must be an HTTP status code")
                return value


        class FixtureMetaFileModel(BaseModel):
            model_config = ConfigDict(extra="allow")

            command_id: str
            captured_at: str | None
            raw_ref: str | None = None
            flow_id: str | None

            @field_validator("command_id")
            @classmethod
            def validate_command_id(cls, value: str) -> str:
                return _validate_command_id(value)

            @field_validator("raw_ref")
            @classmethod
            def validate_raw_ref(cls, value: str | None) -> str | None:
                if value is None:
                    return value
                return _validate_relative_path(value, root="raw")


        class _ProcessorContextCommandModel(BaseModel):
            model_config = ConfigDict(extra="forbid")

            id: str
            cli_path: list[str] = Field(min_length=1)
            summary: str = Field(min_length=1)

            @field_validator("id")
            @classmethod
            def validate_id(cls, value: str) -> str:
                return _validate_command_id(value)

            @field_validator("cli_path")
            @classmethod
            def validate_cli_path(cls, value: list[str]) -> list[str]:
                return [_validate_cli_segment(segment) for segment in value]


        class _ProcessorContextRequestModel(BaseModel):
            model_config = ConfigDict(extra="allow")

            method: str = Field(min_length=1)
            url: str = Field(min_length=1)
            path: str = Field(min_length=1)
            params: dict[str, JsonValue] = Field(default_factory=dict)
            query: dict[str, JsonValue] = Field(default_factory=dict)
            headers: dict[str, str] = Field(default_factory=dict)
            cookies: dict[str, str] = Field(default_factory=dict)
            body: RuntimeBodyValue | None = None

            @field_validator("method")
            @classmethod
            def validate_method(cls, value: str) -> str:
                if value != value.upper():
                    raise ValueError("request methods must be uppercase")
                return value

            @field_validator("path")
            @classmethod
            def validate_path(cls, value: str) -> str:
                if not value.startswith("/"):
                    raise ValueError("paths must start with '/'")
                return value


        class _ProcessorContextResponseModel(BaseModel):
            model_config = ConfigDict(extra="allow")

            status: int | None = None
            headers: dict[str, str] = Field(default_factory=dict)
            cookies: dict[str, str] = Field(default_factory=dict)
            body: RuntimeBodyValue | None = None

            @field_validator("status")
            @classmethod
            def validate_status(cls, value: int | None) -> int | None:
                if value is None:
                    return value
                if value < 100 or value > 599:
                    raise ValueError("status must be an HTTP status code")
                return value


        class _ProcessorContextFixtureModel(BaseModel):
            model_config = ConfigDict(extra="allow")

            id: str | None = None
            captured_at: str | None = None
            raw_ref: str | None = None
            flow_id: str | None = None

            @field_validator("id")
            @classmethod
            def validate_id(cls, value: str | None) -> str | None:
                if value is None:
                    return value
                return _validate_case_id(value)


        class ProcessorContextModel(BaseModel):
            model_config = ConfigDict(extra="allow")

            phase: Literal["pre", "post"]
            execution_mode: Literal["live", "fixture"]
            raw_mode: bool
            command: _ProcessorContextCommandModel
            args: dict[str, JsonValue] = Field(default_factory=dict)
            request: _ProcessorContextRequestModel
            response: _ProcessorContextResponseModel
            fixture: _ProcessorContextFixtureModel
            state: dict[str, Any] = Field(default_factory=dict)
            output: JsonValue | None = None


        def load_workspace_settings(workspace_root: Path) -> dict[str, object]:
            \"\"\"Load [tool.autocli] settings from the generated workspace.\"\"\"

            with (workspace_root / "pyproject.toml").open("rb") as handle:
                data = tomllib.load(handle)
            settings = dict(data.get("tool", {}).get("autocli", {}))
            project = data.get("project", {})
            if isinstance(project, dict) and isinstance(project.get("name"), str):
                settings["project_name"] = project["name"]
            return settings


        def build_app(workspace_root: Path) -> typer.Typer:
            \"\"\"Build the generated site CLI app.\"\"\"

            load_dotenv(workspace_root / ".env", override=False)
            settings = load_workspace_settings(workspace_root)
            app = typer.Typer(
                add_completion=False,
                help=f"Generated CLI for {settings.get('project_name', settings.get('site_slug', '__SITE_SLUG__'))}.",
                no_args_is_help=True,
            )

            @app.callback()
            def main() -> None:
                \"\"\"Generated site CLI root.\"\"\"

            test_mode = os.environ.get(TEST_MODE_ENV) == "true"
            valid_commands, warnings = discover_valid_commands(
                workspace_root,
                include_incomplete=test_mode,
            )
            for warning in warnings:
                emit_runtime_warning(warning)
            register_valid_commands(app, workspace_root, valid_commands)
            return app


        def discover_valid_commands(
            workspace_root: Path,
            *,
            include_incomplete: bool = False,
        ) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
            \"\"\"Discover, validate, and filter runnable command modules.\"\"\"

            warnings: list[dict[str, str]] = []
            passing: list[dict[str, object]] = []

            for command_dir in list_command_dirs(workspace_root):
                command_id = command_dir.name
                try:
                    command_file = load_command_file(command_dir)
                    command_id = command_file.command.id
                except Exception as exc:
                    warnings.append(
                        build_warning(
                            command_id=command_id,
                            command_dir=command_dir,
                            reason="command-file",
                            summary=summarize_exception(exc),
                        )
                    )
                    continue

                if not command_file.command.complete and not include_incomplete:
                    continue

                passing.append({"command_dir": command_dir, "command_file": command_file})

            return filter_duplicate_cli_paths(passing, warnings), warnings


        def list_command_dirs(workspace_root: Path) -> list[Path]:
            \"\"\"List command directories that contain ``command.yaml``.\"\"\"

            command_root = workspace_root / "commands"
            if not command_root.exists():
                return []
            command_dirs = []
            for path in sorted(command_root.iterdir(), key=lambda item: item.name):
                if path.is_dir() and (path / "command.yaml").exists():
                    command_dirs.append(path)
            return command_dirs


        def load_command_file(command_dir: Path) -> CommandFileModel:
            \"\"\"Load and validate one command file.\"\"\"

            payload = yaml.safe_load((command_dir / "command.yaml").read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("command.yaml must contain a mapping")
            return CommandFileModel.model_validate(payload)


        def summarize_exception(exc: Exception) -> str:
            \"\"\"Summarize an exception for startup warnings.\"\"\"

            return str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__


        def build_warning(*, command_id: str, command_dir: Path, reason: str, summary: str) -> dict[str, str]:
            \"\"\"Build a runtime warning payload.\"\"\"

            return {
                "command_id": command_id,
                "command_dir": str(command_dir),
                "reason": reason,
                "summary": summary,
            }


        def emit_runtime_warning(warning: dict[str, str]) -> None:
            \"\"\"Emit one runtime validation warning.\"\"\"

            typer.echo(
                "warning: "
                f"command_id={warning['command_id']} "
                f"command_dir={warning['command_dir']} "
                f"reason={warning['reason']} "
                f"summary={warning['summary']}",
                err=True,
            )


        def filter_duplicate_cli_paths(
            passing: list[dict[str, object]],
            warnings: list[dict[str, str]],
        ) -> list[dict[str, object]]:
            \"\"\"Reject duplicate cli paths among commands whose tests passed.\"\"\"

            grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
            for entry in passing:
                command_file = entry["command_file"]
                grouped[tuple(command_file.command.cli_path)].append(entry)

            filtered: list[dict[str, object]] = []
            for cli_path, entries in grouped.items():
                if len(entries) == 1:
                    filtered.append(entries[0])
                    continue
                path_text = " ".join(cli_path)
                for entry in entries:
                    command_file = entry["command_file"]
                    warnings.append(
                        build_warning(
                            command_id=command_file.command.id,
                            command_dir=entry["command_dir"],
                            reason="duplicate-cli-path",
                            summary=f"Duplicate cli_path: {path_text}",
                        )
                    )
            return filtered


        def register_valid_commands(
            app: typer.Typer,
            workspace_root: Path,
            command_entries: list[dict[str, object]],
        ) -> None:
            \"\"\"Register validated commands onto the Typer app.\"\"\"

            groups: dict[tuple[str, ...], typer.Typer] = {(): app}
            for entry in command_entries:
                register_command(groups, workspace_root, entry["command_dir"], entry["command_file"])


        def register_command(
            groups: dict[tuple[str, ...], typer.Typer],
            workspace_root: Path,
            command_dir: Path,
            command_file: CommandFileModel,
        ) -> None:
            \"\"\"Register one validated command.\"\"\"

            cli_path = list(command_file.command.cli_path)
            parent = get_or_create_group(groups, cli_path[:-1])
            callback = create_command_callback(workspace_root, command_dir, command_file)
            parent.command(
                name=cli_path[-1],
                help=command_file.command.description or command_file.command.summary,
                short_help=command_file.command.summary,
            )(callback)


        def get_or_create_group(groups: dict[tuple[str, ...], typer.Typer], path: list[str]) -> typer.Typer:
            \"\"\"Get or create nested Typer groups for intermediate cli path segments.\"\"\"

            key = tuple(path)
            if key in groups:
                return groups[key]
            parent = get_or_create_group(groups, path[:-1])
            sub_app = typer.Typer(add_completion=False, no_args_is_help=True)
            parent.add_typer(sub_app, name=path[-1])
            groups[key] = sub_app
            return sub_app


        def create_command_callback(
            workspace_root: Path,
            command_dir: Path,
            command_file: CommandFileModel,
        ):
            \"\"\"Create a Typer callback with a dynamic signature for one command.\"\"\"

            def callback(**kwargs: Any) -> None:
                raw_mode = bool(kwargs.pop("raw"))
                replay_mode = bool(kwargs.pop("replay"))
                output_path = kwargs.pop("output")
                try:
                    if replay_mode and os.environ.get(TEST_MODE_ENV) != "true":
                        raise ValueError("--replay is only available when AUTOCLI_TEST_MODE=true")
                    result = execute_command(
                        workspace_root=workspace_root,
                        command_dir=command_dir,
                        command_file=command_file,
                        provided_args=kwargs,
                        raw_mode=raw_mode,
                        replay_mode=replay_mode,
                    )
                    if raw_mode:
                        write_raw_output(result, output_path)
                    else:
                        if output_path is not None:
                            raise ValueError("--output may only be used together with --raw")
                        typer.echo(render_json_output(result))
                except Exception as exc:
                    typer.echo(summarize_exception(exc), err=True)
                    raise typer.Exit(code=1) from exc

            callback.__name__ = f"command_{command_file.command.id}"
            callback.__signature__ = build_callback_signature(command_file)
            return callback


        def build_callback_signature(command_file: CommandFileModel) -> inspect.Signature:
            \"\"\"Build a dynamic callback signature for a generated command.\"\"\"

            parameters: list[inspect.Parameter] = []
            for argument in command_file.command.arguments:
                parameter_type = python_type_for_argument(argument)
                option_name = f"--{argument.name}"
                help_text = argument.help or command_file.command.summary
                if argument.kind == "argument":
                    default = typer.Argument(... if argument.required else argument.default, help=help_text)
                else:
                    option_default = argument.default if argument.default is not None else (... if argument.required else None)
                    default = typer.Option(option_default, option_name, help=help_text)
                parameters.append(
                    inspect.Parameter(
                        argument.python_name,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        default=default,
                        annotation=parameter_type,
                    )
                )

            parameters.append(
                inspect.Parameter(
                    "raw",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=typer.Option(False, "--raw", help="Return the raw response body unchanged."),
                    annotation=bool,
                )
            )
            parameters.append(
                inspect.Parameter(
                    "replay",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=typer.Option(False, "--replay", help="Replay a matching fixture instead of sending a live request."),
                    annotation=bool,
                )
            )
            parameters.append(
                inspect.Parameter(
                    "output",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=typer.Option(None, "--output", help="Write raw output to a file."),
                    annotation=Path | None,
                )
            )
            return inspect.Signature(parameters=parameters)


        def python_type_for_argument(argument: CommandArgumentModel) -> type[Any]:
            \"\"\"Map generated CLI argument types to Python types.\"\"\"

            if argument.type == "string":
                return str
            if argument.type == "integer":
                return int
            if argument.type == "number":
                return float
            return bool


        def execute_command(
            *,
            workspace_root: Path,
            command_dir: Path,
            command_file: CommandFileModel,
            provided_args: dict[str, Any],
            raw_mode: bool,
            replay_mode: bool = False,
            fixture_id: str | None = None,
        ) -> JsonValue | str | bytes:
            \"\"\"Execute a generated command live or from a fixture replay.\"\"\"

            args = normalize_cli_args(command_file, provided_args)
            execution_mode: Literal["live", "fixture"] = "fixture" if replay_mode or fixture_id is not None else "live"
            context = build_base_context(command_file, args, raw_mode=raw_mode, execution_mode=execution_mode)
            apply_request_mapping(context, command_file.command.request_mapping)
            render_request_target(context["request"])
            context = ProcessorContextModel.model_validate(context).model_dump(mode="python")

            pre_processor = load_processor_callable(workspace_root, command_dir, command_file.command.processors.pre)
            context = invoke_processor(pre_processor, context, "pre")
            context = ProcessorContextModel.model_validate(context).model_dump(mode="python")

            if fixture_id is None and replay_mode:
                fixture_id = single_replay_fixture_id(command_file)

            if fixture_id is None:
                perform_live_request(context)
            else:
                apply_live_header_overrides(context, required=True)
                replay_fixture_response(command_dir, command_file, fixture_id, context)

            context = ProcessorContextModel.model_validate(context).model_dump(mode="python")
            if raw_mode:
                return context["response"]["body"]

            context["phase"] = "post"
            post_processor = load_processor_callable(workspace_root, command_dir, command_file.command.processors.post)
            context = invoke_processor(post_processor, context, "post")
            context = ProcessorContextModel.model_validate(context).model_dump(mode="python")
            if "output" not in context or context["output"] is None:
                raise ValueError("Post-processor must set context['output']")
            return validate_json_output(context["output"])


        def normalize_cli_args(command_file: CommandFileModel, provided_args: dict[str, Any]) -> dict[str, JsonValue]:
            \"\"\"Apply defaults and enforce generated argument constraints.\"\"\"

            normalized: dict[str, JsonValue] = {}
            for argument in command_file.command.arguments:
                if argument.python_name in provided_args and provided_args[argument.python_name] is not None:
                    value = provided_args[argument.python_name]
                elif argument.default is not None:
                    value = argument.default
                elif argument.required:
                    raise ValueError(f"Missing required argument {argument.python_name}")
                else:
                    continue

                if argument.choices and value not in argument.choices:
                    choices_text = ", ".join(str(choice) for choice in argument.choices)
                    raise ValueError(f"Invalid value for {argument.python_name}. Expected one of: {choices_text}")
                normalized[argument.python_name] = value
            return normalized


        def build_base_context(
            command_file: CommandFileModel,
            args: dict[str, JsonValue],
            *,
            raw_mode: bool,
            execution_mode: Literal["live", "fixture"],
        ) -> dict[str, Any]:
            \"\"\"Build the shared processor context before request mapping.\"\"\"

            request_payload = command_file.command.request.model_dump(mode="python")
            request_headers = normalize_header_mapping_for_context(request_payload.get("headers", {}))
            context = {
                "phase": "pre",
                "execution_mode": execution_mode,
                "raw_mode": raw_mode,
                "command": {
                    "id": command_file.command.id,
                    "cli_path": list(command_file.command.cli_path),
                    "summary": command_file.command.summary,
                },
                "args": copy.deepcopy(args),
                "request": {
                    "method": request_payload["method"],
                    "url": request_payload["url_template"],
                    "path": request_payload["path_template"],
                    "url_template": request_payload["url_template"],
                    "path_template": request_payload["path_template"],
                    "params": copy.deepcopy(request_payload.get("params", {})),
                    "query": copy.deepcopy(request_payload.get("query", {})),
                    "headers": request_headers,
                    "cookies": copy.deepcopy(request_payload.get("cookies", {})),
                    "body": copy.deepcopy(request_payload.get("body")),
                },
                "response": {
                    "status": None,
                    "headers": {},
                    "cookies": {},
                    "body": None,
                },
                "fixture": {
                    "id": None,
                    "captured_at": None,
                    "raw_ref": None,
                    "flow_id": None,
                },
                "state": {},
                "output": None,
            }
            return context


        def normalize_header_mapping_for_context(mapping: dict[str, HeaderValue]) -> dict[str, str]:
            \"\"\"Normalize command header defaults for processor context validation.\"\"\"

            normalized: dict[str, str] = {}
            for key, value in mapping.items():
                if isinstance(value, list):
                    normalized[key] = ", ".join(str(item) for item in value)
                else:
                    normalized[key] = str(value)
            return normalized


        def apply_request_mapping(context: dict[str, Any], request_mapping: dict[str, JsonValue]) -> None:
            \"\"\"Apply request_mapping in YAML declaration order.\"\"\"

            for target, source in request_mapping.items():
                value = resolve_mapping_source(context["args"], source)
                if value is _SKIP_REQUEST_MAPPING:
                    continue
                set_mapping_target(context, target, value)


        def resolve_mapping_source(args: dict[str, JsonValue], source: JsonValue) -> JsonValue:
            \"\"\"Resolve a request_mapping source expression or literal.\"\"\"

            if not isinstance(source, str):
                return copy.deepcopy(source)
            if not source.startswith("args."):
                return copy.deepcopy(source)
            python_name = source.split(".", 1)[1]
            if python_name not in args:
                return _SKIP_REQUEST_MAPPING
            return copy.deepcopy(args[python_name])


        def set_mapping_target(context: dict[str, Any], target: str, value: JsonValue) -> None:
            \"\"\"Write a request_mapping value into the runtime context.\"\"\"

            parts = target.split(".")
            request = context["request"]
            if parts[1] in {"params", "query", "headers", "cookies"}:
                request[parts[1]][parts[2]] = value
                return
            if parts[1] != "body":
                raise ValueError(f"Unsupported request_mapping target {target}")
            if len(parts) == 2:
                request["body"] = copy.deepcopy(value)
                return

            if request["body"] is None:
                request["body"] = {}
            if not isinstance(request["body"], dict):
                raise ValueError("request.body must be a mapping before writing request.body.<path>")

            cursor = request["body"]
            for part in parts[2:-1]:
                existing = cursor.get(part)
                if existing is None:
                    cursor[part] = {}
                    existing = cursor[part]
                if not isinstance(existing, dict):
                    raise ValueError(f"Cannot write nested body path through non-object field {part}")
                cursor = existing
            cursor[parts[-1]] = copy.deepcopy(value)


        def render_request_target(request: dict[str, Any]) -> None:
            \"\"\"Render the live request URL and path from params.\"\"\"

            params = request.get("params", {})
            request["path"] = substitute_template(request["path_template"], params)
            request["url"] = substitute_template(request["url_template"], params)


        def substitute_template(template: str, params: dict[str, Any]) -> str:
            \"\"\"Render ``{param}`` placeholders in a template string.\"\"\"

            def replacer(match: re.Match[str]) -> str:
                name = match.group(1)
                if name not in params:
                    raise ValueError(f"Missing path parameter {name}")
                return urllib.parse.quote(str(params[name]), safe="")

            return re.sub(r"\\{([^{}]+)\\}", replacer, template)


        def invoke_processor(processor: Any, context: dict[str, Any], phase: str) -> dict[str, Any]:
            \"\"\"Invoke a generated processor and enforce the shared contract.\"\"\"

            result = processor(context)
            if not isinstance(result, dict):
                raise ValueError(f"{phase}-processor must return dict[str, object]")
            return result


        def load_processor_callable(workspace_root: Path, command_dir: Path, module_ref: str):
            \"\"\"Load a processor module from a command directory without cross-command module collisions.\"\"\"

            previous_sys_path = list(sys.path)
            previous_modules = {
                name: module
                for name, module in sys.modules.items()
                if name == "processors" or name.startswith("processors.")
            }
            try:
                for name in list(sys.modules):
                    if name == "processors" or name.startswith("processors."):
                        sys.modules.pop(name)
                sys.path.insert(0, str(workspace_root))
                sys.path.insert(0, str(command_dir))
                importlib.invalidate_caches()
                module = importlib.import_module(module_ref)
            finally:
                sys.path[:] = previous_sys_path
                for name in list(sys.modules):
                    if name == "processors" or name.startswith("processors."):
                        sys.modules.pop(name)
                sys.modules.update(previous_modules)

            processor = getattr(module, "run", None)
            if not callable(processor):
                raise ValueError(f"Processor module {module_ref} must export callable run(context)")
            return processor


        def single_replay_fixture_id(command_file: CommandFileModel) -> str:
            \"\"\"Return the single fixture id for a generated command.\"\"\"

            if len(command_file.command.fixtures) != 1:
                raise ValueError("Replay requires commands to have exactly one fixture")
            return command_file.command.fixtures[0].id


        def replay_fixture_response(
            command_dir: Path,
            command_file: CommandFileModel,
            fixture_id: str,
            context: dict[str, Any],
        ) -> None:
            \"\"\"Replay a fixture response into the processor context.\"\"\"

            fixture_bundle = load_fixture_bundle(command_dir, command_file, fixture_id)
            response_headers = normalize_header_mapping_for_context(fixture_bundle["response"].headers)
            content_type = first_mapping_value(response_headers, "content-type")
            content_encoding = first_mapping_value(response_headers, "content-encoding")
            response_body = decode_content_encoded_body(fixture_bundle["response_body"], content_encoding)
            context["response"] = {
                "status": fixture_bundle["response"].status,
                "headers": response_headers,
                "cookies": {},
                "body": coerce_response_body(response_body, content_type),
            }
            context["fixture"] = {
                "id": fixture_id,
                "captured_at": fixture_bundle["meta"].captured_at,
                "raw_ref": fixture_bundle["meta"].raw_ref,
                "flow_id": fixture_bundle["meta"].flow_id,
            }


        def load_fixture_bundle(
            command_dir: Path,
            command_file: CommandFileModel,
            fixture_id: str,
        ) -> dict[str, Any]:
            \"\"\"Load a validated fixture case bundle.\"\"\"

            fixture_ref = next((fixture for fixture in command_file.command.fixtures if fixture.id == fixture_id), None)
            if fixture_ref is None:
                raise ValueError(f"Unknown fixture id {fixture_id}")
            fixture_dir = command_dir / fixture_ref.path
            if not fixture_dir.exists():
                raise FileNotFoundError(f"Missing fixture directory {fixture_dir}")

            request_payload = json.loads((fixture_dir / "request.json").read_text(encoding="utf-8"))
            response_payload = json.loads((fixture_dir / "response.json").read_text(encoding="utf-8"))
            meta_payload = json.loads((fixture_dir / "meta.json").read_text(encoding="utf-8"))

            return {
                "fixture_ref": fixture_ref,
                "request": FixtureRequestFileModel.model_validate(request_payload),
                "request_body": (fixture_dir / "request.body").read_bytes(),
                "response": FixtureResponseFileModel.model_validate(response_payload),
                "response_body": (fixture_dir / "response.body").read_bytes(),
                "meta": FixtureMetaFileModel.model_validate(meta_payload),
            }


        def load_approved_golden(command_dir: Path, command_file: CommandFileModel, fixture_id: str) -> JsonValue:
            \"\"\"Load and validate the approved golden for one fixture id.\"\"\"

            golden_ref = next((golden for golden in command_file.command.goldens if golden.id == fixture_id), None)
            if golden_ref is None:
                raise ValueError(f"Missing golden reference for fixture {fixture_id}")
            golden_path = command_dir / golden_ref.path
            if not golden_path.exists():
                raise FileNotFoundError(f"Missing golden file {golden_path}")
            return validate_approved_golden(json.loads(golden_path.read_text(encoding="utf-8")))


        def perform_live_request(context: dict[str, Any]) -> None:
            \"\"\"Execute the live HTTP request for a validated command context.\"\"\"

            request = context["request"]
            render_request_target(request)
            apply_live_header_overrides(context, required=False)

            headers = dict(request["headers"])
            payload = serialize_request_body(first_mapping_value(headers, "content-type"), request.get("body"))

            with httpx.Client(follow_redirects=True) as client:
                response = client.request(
                    request["method"],
                    request["url"],
                    params=request.get("query") or None,
                    headers=headers or None,
                    cookies=request.get("cookies") or None,
                    content=payload,
                )

            response_headers = normalize_httpx_headers(response.headers)
            content_type = first_mapping_value(response_headers, "content-type")
            context["response"] = {
                "status": response.status_code,
                "headers": response_headers,
                "cookies": dict(response.cookies),
                "body": coerce_response_body(response.content, content_type),
            }


        def apply_live_header_overrides(context: dict[str, Any], *, required: bool) -> None:
            \"\"\"Merge late-bound session headers into the request context.\"\"\"

            context["request"]["headers"].update(load_live_header_overrides(required=required))


        def load_live_header_overrides(*, required: bool = False) -> dict[str, str]:
            \"\"\"Load late-bound live-session headers from a Playwright request dump.\"\"\"

            raw = os.environ.get(PLAYWRIGHT_HEADERS_JSON_ENV)
            if not raw:
                if required:
                    raise ValueError(f"{PLAYWRIGHT_HEADERS_JSON_ENV} is required for generated fixture tests")
                return {}
            return parse_playwright_header_overrides(raw)


        def parse_playwright_header_overrides(raw: str) -> dict[str, str]:
            \"\"\"Extract session-sensitive headers from Playwright request.allHeaders() JSON.\"\"\"

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{PLAYWRIGHT_HEADERS_JSON_ENV} must be a valid JSON object") from exc

            if not isinstance(payload, dict):
                raise ValueError(f"{PLAYWRIGHT_HEADERS_JSON_ENV} must be a JSON object")
            headers = payload.get("headers")
            if not isinstance(headers, dict):
                raise ValueError(f"{PLAYWRIGHT_HEADERS_JSON_ENV} must contain a headers object")

            overrides: dict[str, str] = {}
            for name, value in headers.items():
                header_name = str(name).lower()
                if header_name.startswith(":"):
                    continue
                if not is_session_sensitive_header(header_name):
                    continue
                if not isinstance(value, str):
                    raise ValueError(f"{PLAYWRIGHT_HEADERS_JSON_ENV} header {header_name!r} must be a string")
                overrides[header_name] = value
            return overrides


        def is_session_sensitive_header(header_name: str) -> bool:
            \"\"\"Return whether a header should be supplied only at runtime.\"\"\"

            normalized = header_name.lower()
            if normalized in SESSION_SENSITIVE_HEADER_NAMES:
                return True
            if normalized.startswith("sec-"):
                return True
            return any(token in normalized for token in SESSION_SENSITIVE_HEADER_SUBSTRINGS)


        def serialize_request_body(content_type: str | None, body: Any) -> bytes | None:
            \"\"\"Serialize a request body using the final content-type header.\"\"\"

            media_type = extract_media_type(content_type)
            charset = extract_charset(content_type) or "utf-8"
            if media_type == "application/json":
                return json.dumps(body, ensure_ascii=False).encode("utf-8")
            if media_type == "application/x-www-form-urlencoded":
                if not isinstance(body, dict):
                    raise ValueError("Form-encoded requests require a mapping body")
                return urllib.parse.urlencode(flatten_for_urlencode(body)).encode("utf-8")
            if media_type == "application/msgpack":
                return msgpack.packb(body, use_bin_type=True)
            if media_type and media_type.startswith("text/"):
                if not isinstance(body, str):
                    raise ValueError("Text request bodies must be strings")
                return body.encode(charset)
            if body is None:
                return None
            if media_type is None:
                if isinstance(body, (dict, list)):
                    return json.dumps(body, ensure_ascii=False).encode("utf-8")
                if isinstance(body, str):
                    return body.encode("utf-8")
                if isinstance(body, bytes):
                    return body
                raise ValueError("Unsupported request body without content-type")
            if isinstance(body, bytes):
                return body
            raise ValueError("Incompatible content-type and request body")


        def flatten_for_urlencode(body: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
            \"\"\"Flatten nested form payloads using dotted keys.\"\"\"

            items: list[tuple[str, Any]] = []
            for key, value in body.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    items.extend(flatten_for_urlencode(value, full_key))
                else:
                    items.append((full_key, value))
            return items


        def coerce_response_body(body: bytes, content_type: str | None) -> str | bytes:
            \"\"\"Preserve text responses as text and binary responses as bytes.\"\"\"

            media_type = extract_media_type(content_type)
            charset = extract_charset(content_type) or "utf-8"
            if media_type and (
                media_type.startswith("text/")
                or media_type == "application/json"
                or media_type.endswith("+json")
                or media_type.endswith("/xml")
                or media_type.endswith("+xml")
                or media_type == "application/javascript"
            ):
                return body.decode(charset)
            return body


        def decode_content_encoded_body(body: bytes, content_encoding: str | None) -> bytes:
            \"\"\"Decode HTTP content-encoding layers captured in fixture bodies.\"\"\"

            if not content_encoding:
                return body

            decoded = body
            encodings = [item.strip().lower() for item in content_encoding.split(",") if item.strip()]
            for encoding in reversed(encodings):
                if encoding in {"identity"}:
                    continue
                if encoding in {"gzip", "x-gzip"}:
                    decoded = gzip.decompress(decoded)
                    continue
                if encoding == "deflate":
                    try:
                        decoded = zlib.decompress(decoded)
                    except zlib.error:
                        decoded = zlib.decompress(decoded, -zlib.MAX_WBITS)
                    continue
                if encoding == "br":
                    try:
                        import brotli
                    except ImportError as exc:
                        raise ValueError("brotli content-encoding requires the brotli package") from exc
                    decoded = brotli.decompress(decoded)
                    continue
                if encoding in {"zstd", "x-zstd"}:
                    try:
                        import zstandard
                    except ImportError as exc:
                        raise ValueError("zstd content-encoding requires the zstandard package") from exc
                    decoded = zstandard.ZstdDecompressor().decompress(decoded)
                    continue
                raise ValueError(f"Unsupported content-encoding {encoding!r}")
            return decoded


        def decode_body_bytes(body: bytes | None, content_type: str | None) -> Any:
            \"\"\"Decode boundary body bytes for testing helpers.\"\"\"

            if body is None or body == b"":
                return None
            media_type = extract_media_type(content_type)
            charset = extract_charset(content_type) or "utf-8"
            if media_type in {"application/json", "application/ld+json"} or (media_type and media_type.endswith("+json")):
                return json.loads(body.decode(charset))
            if media_type in {"application/msgpack", "application/x-msgpack"}:
                return msgpack.unpackb(body, raw=False)
            if media_type == "application/x-www-form-urlencoded":
                pairs = urllib.parse.parse_qsl(body.decode(charset), keep_blank_values=True)
                result: dict[str, str | list[str]] = {}
                for key, value in pairs:
                    existing = result.get(key)
                    if existing is None:
                        result[key] = value
                    elif isinstance(existing, list):
                        existing.append(value)
                    else:
                        result[key] = [existing, value]
                return result
            if media_type and media_type.startswith("text/"):
                return body.decode(charset)
            return body


        def extract_media_type(content_type: str | None) -> str | None:
            \"\"\"Extract a media type from Content-Type.\"\"\"

            if not content_type:
                return None
            return content_type.split(";", 1)[0].strip().lower() or None


        def extract_charset(content_type: str | None) -> str | None:
            \"\"\"Extract a charset parameter from Content-Type.\"\"\"

            if not content_type:
                return None
            parts = [part.strip() for part in content_type.split(";")]
            for part in parts[1:]:
                if part.lower().startswith("charset="):
                    return part.split("=", 1)[1].strip() or None
            return None


        def normalize_httpx_headers(headers: httpx.Headers) -> dict[str, str]:
            \"\"\"Normalize HTTPX response headers for processor context.\"\"\"

            normalized: dict[str, str] = {}
            for key, value in headers.multi_items():
                lower = key.lower()
                if lower in normalized:
                    normalized[lower] = normalized[lower] + ", " + value
                else:
                    normalized[lower] = value
            return normalized


        def first_mapping_value(mapping: dict[str, Any], key: str) -> str | None:
            \"\"\"Return the first string value for a normalized mapping key.\"\"\"

            value = mapping.get(key)
            if value is None:
                return None
            if isinstance(value, list):
                return str(value[0]) if value else None
            return str(value)


        def validate_json_output(value: Any) -> JsonValue:
            \"\"\"Validate that a command output is JSON-serializable.\"\"\"

            return validate_approved_golden(value)


        def canonical_json(value: Any) -> str:
            \"\"\"Canonicalize a JSON value for comparison.\"\"\"

            return json.dumps(validate_json_output(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


        def render_json_output(value: Any) -> str:
            \"\"\"Render a JSON value for CLI stdout.\"\"\"

            return json.dumps(validate_json_output(value), indent=2, sort_keys=True, ensure_ascii=False)


        def write_raw_output(payload: str | bytes, output_path: Path | None) -> None:
            \"\"\"Write raw output to stdout or a file.\"\"\"

            if output_path is not None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(payload, bytes):
                    output_path.write_bytes(payload)
                else:
                    output_path.write_text(payload, encoding="utf-8")
                return

            if isinstance(payload, bytes):
                if sys.stdout.isatty():
                    raise ValueError("Raw binary output requires redirected stdout or --output PATH")
                sys.stdout.buffer.write(payload)
                sys.stdout.buffer.flush()
                return

            sys.stdout.write(payload)
            sys.stdout.flush()
        """
    ).replace("__SITE_SLUG__", site_slug)
