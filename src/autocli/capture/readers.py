"""Capture readers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mitmproxy import http, io

from autocli.capture.formats import CaptureFormat, detect_capture_format


def read_capture(path: Path, *, requested_format: CaptureFormat = "auto") -> list[dict[str, Any]]:
    """Read a capture file into raw exchange records."""

    capture_format = detect_capture_format(path, requested_format=requested_format)
    if capture_format == "flow":
        return read_flow_capture(path)

    raise AssertionError(f"unexpected capture format: {capture_format}")


def read_flow_capture(path: Path) -> list[dict[str, Any]]:
    """Read a mitmproxy flow capture."""

    exchanges: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        reader = io.FlowReader(handle)
        for index, flow in enumerate(reader.stream(), start=1):
            if not isinstance(flow, http.HTTPFlow):
                continue
            if flow.request is None or flow.response is None:
                continue

            exchanges.append(
                {
                    "source": {
                        "format": "flow",
                        "source_path": str(path),
                        "capture_id": str(index),
                        "captured_at": flow.request.timestamp_start,
                    },
                    "request": {
                        "method": flow.request.method,
                        "url": flow.request.pretty_url or flow.request.url,
                        "scheme": flow.request.scheme,
                        "host": flow.request.host,
                        "port": flow.request.port,
                        "host_header": flow.request.host_header,
                        "path": flow.request.path,
                        "headers": list(flow.request.headers.items(multi=True)),
                        "body": bytes(flow.request.raw_content or b""),
                    },
                    "response": {
                        "status": flow.response.status_code,
                        "headers": list(flow.response.headers.items(multi=True)),
                        "body": bytes(flow.response.raw_content or b""),
                    },
                }
            )
    return exchanges
