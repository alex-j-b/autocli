"""Capture format helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

CaptureFormat = Literal["auto", "flow"]
ResolvedCaptureFormat = Literal["flow"]

SUPPORTED_CAPTURE_FORMATS = ("auto", "flow")


def detect_capture_format(path: Path, *, requested_format: CaptureFormat = "auto") -> ResolvedCaptureFormat:
    """Detect the concrete capture format."""

    if requested_format not in SUPPORTED_CAPTURE_FORMATS:
        raise ValueError(f"unsupported capture format {requested_format!r}")
    if requested_format != "auto":
        return requested_format

    suffix = path.suffix.lower()
    if suffix == ".flow":
        return "flow"

    return "flow"
