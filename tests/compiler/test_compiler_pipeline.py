from __future__ import annotations

from autocli.compiler import compile_command_candidates, group_exchanges
from tests.support import make_exchange


def test_group_exchanges_derives_parameterized_templates_command_ids_and_cli_paths() -> None:
    exchanges = [
        make_exchange('GET', 'https://shop.example.com/api/products', source_id='1'),
        make_exchange('POST', 'https://shop.example.com/api/products', source_id='2'),
        make_exchange('GET', 'https://shop.example.com/api/products/123', source_id='3'),
        make_exchange('GET', 'https://shop.example.com/api/products/456', source_id='3b'),
        make_exchange('GET', 'https://shop.example.com/api/inventory/123/full', source_id='4'),
        make_exchange('GET', 'https://shop.example.com/api/inventory/456/full', source_id='5'),
        make_exchange('PUT', 'https://shop.example.com/epood/cart/change/123', source_id='6'),
        make_exchange('PUT', 'https://shop.example.com/epood/cart/change/456', source_id='7'),
        make_exchange('GET', 'https://shop.example.com/epood/cart/summary/123', source_id='8'),
        make_exchange('GET', 'https://shop.example.com/epood/cart/summary/456', source_id='9'),
    ]

    groups = group_exchanges(exchanges)
    by_id = {group['command_id']: group for group in groups}

    get_collection = by_id['get__h_shop_example_com__s_api__s_products']
    post_collection = by_id['post__h_shop_example_com__s_api__s_products']
    get_detail = by_id['get__h_shop_example_com__s_api__s_products__p_p1']
    inventory_full = by_id['get__h_shop_example_com__s_api__s_inventory__p_p1__s_full']
    cart_change = by_id['put__h_shop_example_com__s_epood__s_cart__s_change__p_p1']

    assert get_collection['cli_path'] == ['products', 'list']
    assert post_collection['cli_path'] == ['products', 'create']
    assert get_detail['cli_path'] == ['products', 'get']
    assert inventory_full['path_template'] == '/api/inventory/{p1}/full'
    assert inventory_full['cli_path'] == ['inventory', 'full']
    assert cart_change['path_template'] == '/epood/cart/change/{p1}'
    assert cart_change['cli_path'] == ['cart', 'change']
    assert all(group['cli_path_conflict'] is False for group in groups)


def test_compile_command_candidates_infers_summary_schema_arguments_and_request_mapping() -> None:
    exchanges = [
        make_exchange(
            'PUT',
            'https://shop.example.com/epood/cart/change/123?format=json&lang=en',
            request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            request_body=b'{"delta": 1, "mode": "soft"}',
            source_id='1',
        ),
        make_exchange(
            'PUT',
            'https://shop.example.com/epood/cart/change/456?format=table&lang=en',
            request_headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            request_body=b'{"delta": 2, "mode": "soft"}',
            source_id='2',
        ),
    ]

    candidates = compile_command_candidates(exchanges)

    assert len(candidates) == 1
    candidate = candidates[0]
    arguments = {argument['python_name']: argument for argument in candidate['arguments']}

    assert candidate['id'] == 'put__h_shop_example_com__s_epood__s_cart__s_change__p_p1'
    assert candidate['cli_path'] == ['cart', 'change']
    assert candidate['summary'] == 'Change cart'
    assert candidate['request']['path_template'] == '/epood/cart/change/{p1}'
    assert candidate['request']['query'] == {}
    assert candidate['request']['body'] == {}
    assert candidate['request']['headers'] == {
        'content-type': 'application/json',
        'accept': 'application/json',
    }
    assert candidate['request']['query_schema']['properties'] == {
        'format': {'type': 'string'},
        'lang': {'type': 'string'},
    }
    assert candidate['request']['body_schema']['properties'] == {
        'delta': {'type': 'integer'},
        'mode': {'type': 'string'},
    }
    assert arguments['p1']['kind'] == 'argument'
    assert arguments['p1']['type'] == 'integer'
    assert arguments['format']['kind'] == 'option'
    assert arguments['delta']['type'] == 'integer'
    assert candidate['request_mapping'] == {
        'request.params.p1': 'args.p1',
        'request.query.format': 'args.format',
        'request.query.lang': 'en',
        'request.body.delta': 'args.delta',
        'request.body.mode': 'soft',
    }
