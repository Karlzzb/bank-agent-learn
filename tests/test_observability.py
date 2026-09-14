"""Langfuse 可观测性接线:启用条件、trace config 形状、flush 委托。

不碰真实 Langfuse 服务:客户端与 CallbackHandler 均用假实现替换,
只验证"什么时候启用、往图调用 config 里注入了什么"。
"""

import bank_agent.observability as obs
from bank_agent.config import Settings


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.flushed = False

    def flush(self):
        self.flushed = True


class _FakeHandler:
    pass


def _reset():
    obs._client = None


def test_disabled_without_keys():
    _reset()
    try:
        settings = Settings(langfuse_public_key="", langfuse_secret_key="")
        assert obs.configure(settings) is False
        assert obs.trace_config("t1", "C001") == {}
        obs.flush()  # 空操作,不抛异常
    finally:
        _reset()


def test_enabled_with_keys_injects_trace_metadata(monkeypatch):
    _reset()
    fake_client = None

    def fake_langfuse(**kwargs):
        nonlocal fake_client
        fake_client = _FakeClient(**kwargs)
        return fake_client

    monkeypatch.setattr(obs, "Langfuse", fake_langfuse)
    monkeypatch.setattr("langfuse.langchain.CallbackHandler", _FakeHandler)
    try:
        settings = Settings(
            langfuse_public_key="pk-lf-x",
            langfuse_secret_key="sk-lf-y",
            langfuse_base_url="http://localhost:3000",
        )
        assert obs.configure(settings) is True
        assert fake_client.kwargs == {
            "public_key": "pk-lf-x",
            "secret_key": "sk-lf-y",
            "base_url": "http://localhost:3000",
        }

        config = obs.trace_config("thread-1", "C001")
        assert len(config["callbacks"]) == 1
        assert isinstance(config["callbacks"][0], _FakeHandler)
        # 归因维度:会话 / 用户(成本按 model 由 Langfuse 价格表算,Agent 维度在子图 metadata)
        assert config["metadata"]["langfuse_session_id"] == "thread-1"
        assert config["metadata"]["langfuse_user_id"] == "C001"
        assert "bank-agent" in config["metadata"]["langfuse_tags"]

        obs.flush()
        assert fake_client.flushed is True
    finally:
        _reset()
