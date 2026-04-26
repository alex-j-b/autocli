"""Capture format helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

CaptureFormat = Literal['auto', 'flow']
ResolvedCaptureFormat = Literal['flow']

SUPPORTED_CAPTURE_FORMATS = ('auto', 'flow')
SUPPORTED_CAPTURE_PATH_SUFFIXES = ('', '.flow')


def validate_capture_path(path: Path) -> None:
    """Ensure the capture path uses a supported suffix."""

    suffix = path.suffix.lower()
    if suffix in SUPPORTED_CAPTURE_PATH_SUFFIXES:
        return

    raise ValueError(
        f'unsupported capture file extension {path.suffix!r} for {path}; '
        'expected a .flow file or a suffixless flow capture'
    )


def detect_capture_format(path: Path, *, requested_format: CaptureFormat = 'auto') -> ResolvedCaptureFormat:
    """Detect the concrete capture format."""

    if requested_format not in SUPPORTED_CAPTURE_FORMATS:
        raise ValueError(f'unsupported capture format {requested_format!r}')

    validate_capture_path(path)
    if requested_format != 'auto':
        return requested_format
    return 'flow'
