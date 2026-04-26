"""Generated testing template renderers."""

from __future__ import annotations

from textwrap import dedent


def render_testing_module() -> str:
    """Render the generated site package ``testing.py`` module."""

    return dedent(
        """
        \"\"\"Generated workspace-local testing helpers.\"\"\"

        from __future__ import annotations

        from pathlib import Path
        import re
        import urllib.parse
        import yaml

        from .runtime import (
            canonical_json,
            coerce_response_body,
            decode_content_encoded_body,
            decode_body_bytes,
            execute_command,
            first_mapping_value,
            load_approved_golden,
            load_command_file,
            load_fixture_bundle,
        )

        _MISSING = object()


        def mark_command_complete(command_dir: Path, complete: bool) -> None:
            \"\"\"Persist the command completion flag in ``command.yaml``.\"\"\"

            command_dir = Path(command_dir).resolve()
            command_file_path = command_dir / "command.yaml"
            payload = yaml.safe_load(command_file_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("command"), dict):
                raise ValueError(f"Invalid command.yaml structure in {command_file_path}")

            command_payload = payload["command"]
            if command_payload.get("complete") is complete:
                return

            command_payload["complete"] = complete
            command_file_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


        def run_command_contract(command_dir: Path) -> None:
            \"\"\"Run the generated command contract against all fixture/golden pairs.\"\"\"

            command_dir = Path(command_dir).resolve()
            workspace_root = command_dir.parents[1]
            command_file = load_command_file(command_dir)
            try:
                for fixture_ref in command_file.command.fixtures:
                    fixture_bundle = load_fixture_bundle(command_dir, command_file, fixture_ref.id)
                    args = build_fixture_args(command_file, fixture_bundle)
                    response_headers = fixture_bundle["response"].headers
                    content_type = first_mapping_value(response_headers, "content-type")
                    content_encoding = first_mapping_value(response_headers, "content-encoding")
                    expected_raw = coerce_response_body(
                        decode_content_encoded_body(fixture_bundle["response_body"], content_encoding),
                        content_type,
                    )
                    raw_result = execute_command(
                        workspace_root=workspace_root,
                        command_dir=command_dir,
                        command_file=command_file,
                        provided_args=args,
                        raw_mode=True,
                        fixture_id=fixture_ref.id,
                    )
                    assert raw_result == expected_raw

                    golden = load_approved_golden(command_dir, command_file, fixture_ref.id)
                    output = execute_command(
                        workspace_root=workspace_root,
                        command_dir=command_dir,
                        command_file=command_file,
                        provided_args=args,
                        raw_mode=False,
                        fixture_id=fixture_ref.id,
                    )
                    assert canonical_json(output) == canonical_json(golden)
            except Exception:
                mark_command_complete(command_dir, False)
                raise

            mark_command_complete(command_dir, True)


        def build_fixture_args(command_file, fixture_bundle: dict[str, object]) -> dict[str, object]:
            \"\"\"Reconstruct CLI args for one fixture by reversing request_mapping.\"\"\"

            request = fixture_bundle["request"]
            request_body = decode_body_bytes(
                fixture_bundle["request_body"],
                first_mapping_value(request.headers, "content-type"),
            )
            path_params = extract_path_params(command_file.command.request.path_template, request.path)
            mapping_targets = {
                source: target
                for target, source in command_file.command.request_mapping.items()
                if isinstance(source, str) and source.startswith("args.")
            }

            args: dict[str, object] = {}
            for argument in command_file.command.arguments:
                source = f"args.{argument.python_name}"
                target = mapping_targets.get(source)
                if target is None:
                    if argument.default is not None:
                        args[argument.python_name] = argument.default
                    continue
                raw_value = extract_target_value(target=target, request=request, request_body=request_body, path_params=path_params)
                if raw_value is _MISSING:
                    if argument.default is not None:
                        args[argument.python_name] = argument.default
                        continue
                    if argument.required:
                        raise AssertionError(f"Missing required fixture value for {source}")
                    continue
                args[argument.python_name] = coerce_argument_value(argument.type, raw_value)
            return args


        def extract_path_params(path_template: str, concrete_path: str) -> dict[str, str]:
            \"\"\"Extract path params by matching a fixture request path to a template.\"\"\"

            pattern = "^" + re.sub(
                r"\\\\\\{([^{}]+)\\\\\\}",
                lambda match: f"(?P<{match.group(1)}>[^/]+)",
                re.escape(path_template),
            ) + "$"
            match = re.match(pattern, concrete_path)
            if not match:
                raise AssertionError(f"Fixture path {concrete_path!r} does not match template {path_template!r}")
            return {key: urllib.parse.unquote(value) for key, value in match.groupdict().items()}


        def extract_target_value(
            *,
            target: str,
            request,
            request_body,
            path_params: dict[str, str],
        ):
            \"\"\"Extract one request_mapping target value from a fixture bundle.\"\"\"

            parts = target.split(".")
            if parts[:2] == ["request", "params"]:
                return path_params.get(parts[2], _MISSING)
            if parts[:2] == ["request", "query"]:
                value = request.query.get(parts[2], _MISSING)
                if value is _MISSING:
                    return _MISSING
                if isinstance(value, list):
                    raise AssertionError(f"Repeated query values are out of scope for {target}")
                return value
            if parts[:2] == ["request", "headers"]:
                value = request.headers.get(parts[2], _MISSING)
                if value is _MISSING:
                    return _MISSING
                if isinstance(value, list):
                    raise AssertionError(f"Repeated header values are out of scope for {target}")
                return value
            if parts[:2] == ["request", "cookies"]:
                return _MISSING
            if parts[:2] == ["request", "body"]:
                if len(parts) == 2:
                    return request_body
                cursor = request_body
                for part in parts[2:]:
                    if not isinstance(cursor, dict) or part not in cursor:
                        return _MISSING
                    cursor = cursor[part]
                return cursor
            raise AssertionError(f"Unsupported fixture extraction target {target}")


        def coerce_argument_value(argument_type: str, value):
            \"\"\"Coerce a fixture-derived value back to the declared CLI type.\"\"\"

            if argument_type == "string":
                return str(value)
            if argument_type == "integer":
                return int(value)
            if argument_type == "number":
                return float(value)
            if argument_type == "boolean":
                if isinstance(value, bool):
                    return value
                lowered = str(value).lower()
                if lowered == "true":
                    return True
                if lowered == "false":
                    return False
                raise AssertionError(f"Cannot coerce {value!r} to boolean")
            raise AssertionError(f"Unsupported argument type {argument_type}")
        """
    )


def render_command_test(site_module: str) -> str:
    """Render the generated per-command pytest module."""

    return dedent(
        """
        \"\"\"Generated command-contract test.\"\"\"

        from __future__ import annotations

        from pathlib import Path

        from __SITE_MODULE__.testing import run_command_contract


        def test_command_contract() -> None:
            run_command_contract(Path(__file__).resolve().parents[1])
        """
    ).replace("__SITE_MODULE__", site_module)
