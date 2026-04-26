from __future__ import annotations

import msgpack
import pytest
from mitmproxy import connection, http, io

from autocli.capture import (
    decode_body_bytes,
    detect_capture_format,
    normalize_exchange,
    read_capture,
    read_flow_capture,
)


def test_detect_capture_format_accepts_flow_and_suffixless_paths(tmp_path) -> None:
    flow_path = tmp_path / 'sample.flow'
    flow_path.write_bytes(b'binary-flow')
    assert detect_capture_format(flow_path) == 'flow'

    suffixless_path = tmp_path / 'capture'
    suffixless_path.write_bytes(b'binary-flow')
    assert detect_capture_format(suffixless_path) == 'flow'


def test_detect_capture_format_rejects_unsupported_suffix(tmp_path) -> None:
    capture_path = tmp_path / 'capture.bin'
    capture_path.write_bytes(b'binary-flow')

    with pytest.raises(
        ValueError,
        match=r"unsupported capture file extension '.bin'.*expected a \.flow file or a suffixless flow capture",
    ):
        detect_capture_format(capture_path)


def test_read_capture_rejects_unsupported_capture_files(tmp_path) -> None:
    capture_path = tmp_path / 'sample.json'
    capture_path.write_text('{}', encoding='utf-8')

    with pytest.raises(
        ValueError,
        match=r"unsupported capture file extension '.json'.*expected a \.flow file or a suffixless flow capture",
    ):
        read_capture(capture_path)

    with pytest.raises(
        ValueError,
        match=r"unsupported capture file extension '.json'.*expected a \.flow file or a suffixless flow capture",
    ):
        read_capture(capture_path, requested_format='flow')


def test_read_flow_capture_skips_flows_without_responses(tmp_path) -> None:
    capture_path = tmp_path / 'sample.flow'

    with capture_path.open('wb') as handle:
        writer = io.FlowWriter(handle)

        incomplete_flow = http.HTTPFlow(
            client_conn=connection.Client(peername=('127.0.0.1', 1111), sockname=('127.0.0.1', 8080)),
            server_conn=connection.Server(address=('example.com', 443)),
        )
        incomplete_flow.request = http.Request.make('GET', 'https://example.com/api/missing')
        writer.add(incomplete_flow)

        complete_flow = http.HTTPFlow(
            client_conn=connection.Client(peername=('127.0.0.1', 1112), sockname=('127.0.0.1', 8080)),
            server_conn=connection.Server(address=('example.com', 443)),
        )
        complete_flow.request = http.Request.make(
            'GET',
            'https://example.com/api/products?lang=en',
            headers={'Host': 'example.com'},
        )
        complete_flow.response = http.Response.make(200, b'{"ok": true}', headers={'Content-Type': 'application/json'})
        writer.add(complete_flow)

    exchanges = read_flow_capture(capture_path)

    assert len(exchanges) == 1
    assert exchanges[0]['request']['url'] == 'https://example.com/api/products?lang=en'
    assert exchanges[0]['response']['status'] == 200


def test_normalize_exchange_repairs_flow_hosts_and_extracts_query() -> None:
    normalized = normalize_exchange(
        {
            'source': {
                'format': 'flow',
                'source_path': '/tmp/sample.flow',
                'capture_id': '1',
                'captured_at': 1_776_000_000.0,
            },
            'request': {
                'method': 'GET',
                'url': 'https:///api/products?lang=en',
                'scheme': 'https',
                'host': 'www.example.com',
                'port': 443,
                'host_header': 'www.example.com',
                'path': '/api/products?lang=en',
                'headers': [('Host', 'www.example.com'), ('Accept', 'application/json')],
                'body': b'',
            },
            'response': {
                'status': 200,
                'headers': [('Content-Type', 'application/json')],
                'body': b'{"ok": true}',
            },
        }
    )

    assert normalized['request']['url'] == 'https://www.example.com/api/products?lang=en'
    assert normalized['request']['host'] == 'www.example.com'
    assert normalized['request']['path'] == '/api/products'
    assert normalized['request']['query'] == {'lang': 'en'}
    assert normalized['response']['media_type'] == 'application/json'


def test_decode_body_bytes_handles_supported_boundary_formats() -> None:
    assert decode_body_bytes(b'{"ok": true}', 'application/json') == {'ok': True}
    assert decode_body_bytes(msgpack.packb({'count': 2}, use_bin_type=True), 'application/msgpack') == {'count': 2}
    assert decode_body_bytes(b'lang=en&mode=soft', 'application/x-www-form-urlencoded') == {
        'lang': 'en',
        'mode': 'soft',
    }
    assert decode_body_bytes(b'tere', 'text/plain; charset=utf-8') == 'tere'
    assert decode_body_bytes(b'\x00\x01', 'application/octet-stream') == b'\x00\x01'
