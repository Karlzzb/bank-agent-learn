"""Langfuse 价格表初始化:payload 形状、幂等跳过、未知模型告警(不碰真实服务)。"""

from bank_agent.config import Settings
from bank_agent.langfuse_setup import MODEL_PRICES, ensure_model_prices, model_payload

_SETTINGS = dict(langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-y")


def test_payload_shape_matches_public_api():
    payload = model_payload("deepseek-chat")
    assert payload["modelName"] == "deepseek-chat"
    assert payload["matchPattern"] == "(?i)^(deepseek-chat)$"
    assert payload["unit"] == "TOKENS"
    # DeepSeek 官方标价:输入 $0.27/M、输出 $1.10/M
    assert payload["inputPrice"] == 0.27e-6
    assert payload["outputPrice"] == 1.10e-6
    assert set(MODEL_PRICES) == {"deepseek-chat", "deepseek-reasoner"}


def test_creates_definition_when_missing():
    calls = []

    def fake_http(settings, method, path, body=None):
        calls.append((method, path, body))
        return {"data": []}

    msg = ensure_model_prices(Settings(llm_model="deepseek-chat", **_SETTINGS), http=fake_http)
    assert "已创建" in msg
    assert calls[0][:2] == ("GET", "/api/public/models")
    assert calls[1][:2] == ("POST", "/api/public/models")
    assert calls[1][2]["modelName"] == "deepseek-chat"


def test_skips_when_definition_exists():
    def fake_http(settings, method, path, body=None):
        assert method == "GET"  # 已存在则不应再 POST
        return {"data": [{"modelName": "deepseek-chat"}]}

    msg = ensure_model_prices(Settings(llm_model="deepseek-chat", **_SETTINGS), http=fake_http)
    assert "已存在" in msg


def test_unknown_model_warns_without_http():
    def fake_http(*args, **kwargs):
        raise AssertionError("未知模型不应发起任何 HTTP 调用")

    msg = ensure_model_prices(Settings(llm_model="some-other-model", **_SETTINGS), http=fake_http)
    assert "跳过" in msg
