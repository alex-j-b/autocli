"""Factory CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer

from autocli.capture import normalize_exchanges, read_capture
from autocli.compiler.schema import compile_command_candidates
from autocli.scaffold import bootstrap_workspace

CaptureFormat = Literal["auto", "flow"]

app = typer.Typer(
    add_completion=False,
    help="Build standalone site CLIs from captured browser traffic.",
    no_args_is_help=True,
)


@app.callback()
def main_callback() -> None:
    """Top-level factory CLI group."""


@app.command()
def build(
    capture_path: Annotated[Path, typer.Argument(help="Path to a .flow capture.")],
    format: Annotated[
        CaptureFormat,
        typer.Option("--format", help="Capture input format."),
    ] = "auto",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Target workspace directory."),
    ] = Path("."),
) -> None:
    """Compile a capture into a generated workspace."""

    if not capture_path.exists():
        raise typer.BadParameter(f"Capture path does not exist: {capture_path}", param_hint="capture_path")

    try:
        raw_exchanges = read_capture(capture_path, requested_format=format)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="capture_path") from exc
    normalized_exchanges = normalize_exchanges(raw_exchanges)
    compiled_commands = compile_command_candidates(normalized_exchanges)

    if not compiled_commands:
        typer.echo("No command-bearing exchanges were accepted from the capture.", err=True)
        raise typer.Exit(code=1)

    try:
        result = bootstrap_workspace(output_dir, compiled_commands=compiled_commands)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    for warning in result["warnings"]:
        typer.echo(f"warning: {warning}", err=True)
    typer.echo(
        f"Workspace {result['workspace_root']}: created {len(result['created_command_ids'])} "
        f"command(s), skipped {len(result['skipped_command_ids'])} duplicate(s)."
    )
    typer.echo(f"Next: uv tool install -e {result['workspace_root']}")
    typer.echo(f"Next: use refinement skill {result['refinement_skill_path']}")


def main() -> None:
    """Run the Typer application."""

    app()
