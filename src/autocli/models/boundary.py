"""Pydantic boundary models for workspace files and processor context."""

from __future__ import annotations

import keyword
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

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
_MODULE_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_PATH_SEGMENT_VALUE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_REQUEST_MAPPING_SOURCE_RE = re.compile(r"^args\.([A-Za-z_][A-Za-z0-9_]*)$")
_REQUEST_MAPPING_TARGET_RE = re.compile(
    r"^(?:"
    r"request\.(?:params|query|headers|cookies)\.[A-Za-z0-9_-]+"
    r"|request\.body(?:\.[A-Za-z0-9_-]+)*"
    r")$"
)


def validate_approved_golden(value: Any) -> JsonValue:
    """Validate an approved golden as a plain JSON value."""

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
    """One canonical path-template segment."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["literal", "parameter"]
    value: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_segment(self) -> PathShapeSegmentModel:
        if self.kind == "literal":
            if "/" in self.value:
                raise ValueError("literal path-shape values must not contain slashes")
            return self
        _validate_python_name(self.value)
        return self


class CommandArgumentModel(BaseModel):
    """Operator-facing CLI argument declaration."""

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
    def validate_argument(self) -> CommandArgumentModel:
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
    """Relative processor-module references."""

    model_config = ConfigDict(extra="forbid")

    pre: str
    post: str

    @field_validator("pre", "post")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        return _validate_module_ref(value)


class FixtureRefModel(BaseModel):
    """Reference to a fixture case directory."""

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
    """Reference to an approved golden file."""

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
    """Recorded request contract used for later live execution."""

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
    """The nested ``command`` object in ``command.yaml``."""

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
    def validate_command(self) -> CommandSpecModel:
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
    """Complete ``command.yaml`` boundary model."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    command: CommandSpecModel


class FixtureRequestFileModel(BaseModel):
    """Recorded request envelope."""

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
    """Recorded response envelope."""

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
    """Recorded fixture provenance."""

    model_config = ConfigDict(extra="allow")

    command_id: str
    captured_at: datetime | None
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
    captured_at: datetime | None = None
    raw_ref: str | None = None
    flow_id: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_case_id(value)


class ProcessorContextModel(BaseModel):
    """Runtime processor context."""

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
