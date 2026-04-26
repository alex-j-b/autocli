"""Generated testing template renderers."""

from __future__ import annotations

from autocli.templating import render_template


def render_testing_module() -> str:
    """Render the generated site package ``testing.py`` module."""

    return render_template("testing/testing.py.j2")


def render_command_test(site_module: str) -> str:
    """Render the generated per-command pytest module."""

    return render_template("testing/command_test.py.j2", site_module=site_module)
