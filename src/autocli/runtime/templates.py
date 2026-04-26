"""Generated runtime template renderers."""

from __future__ import annotations

from autocli.templating import render_template


def render_package_init() -> str:
    """Render the generated site package ``__init__`` module."""

    return render_template("runtime/package_init.py.j2")


def render_package_main() -> str:
    """Render the generated site package ``__main__`` module."""

    return render_template("runtime/package_main.py.j2")


def render_cli_module() -> str:
    """Render the generated site package ``cli.py`` module."""

    return render_template("runtime/cli.py.j2")


def render_runtime_module(site_slug: str) -> str:
    """Render the generated site package runtime helpers."""

    return render_template("runtime/runtime.py.j2", site_slug=site_slug)
