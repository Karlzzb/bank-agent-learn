"""路由决策 JSON 解析:工业级容错。"""

import pytest

from bank_agent.routing import RouteParseError, parse_route_decision


def test_parse_plain_json():
    decision = parse_route_decision('{"target": "accounts", "rationale": "查余额"}')
    assert decision.target == "accounts"
    assert decision.rationale == "查余额"


def test_parse_fenced_json():
    text = '好的,路由结果:\n```json\n{"target": "service", "rationale": "改地址"}\n```'
    assert parse_route_decision(text).target == "service"


def test_parse_json_with_surrounding_text():
    text = '我认为应该这样 {"target": "clarify", "question": "您要办什么?"} 完毕'
    decision = parse_route_decision(text)
    assert decision.target == "clarify"
    assert decision.question == "您要办什么?"


def test_parse_trailing_garbage_after_object():
    decision = parse_route_decision('{"target": "transactions"}{"extra": true}')
    assert decision.target == "transactions"


def test_reject_no_json():
    with pytest.raises(RouteParseError):
        parse_route_decision("我不知道怎么路由")


def test_reject_invalid_json():
    with pytest.raises(RouteParseError):
        parse_route_decision('{"target": "accounts", }')


def test_reject_unknown_target():
    with pytest.raises(RouteParseError):
        parse_route_decision('{"target": "贷款审批"}')
