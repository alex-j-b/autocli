"""Shared Jinja2 template rendering helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("autocli", "template_assets"),
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )


def render_template(template_name: str, /, **context: Any) -> str:
    """Render a packaged text template."""

    return _environment().get_template(template_name).render(**context)
