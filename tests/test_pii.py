"""PII 脱敏组件:确定性规则的单元测试。"""

from bank_agent.pii import mask_text, rehydrate


def test_mask_phone_id_card_and_card():
    mapping: dict[str, str] = {}
    text = mask_text("手机 13800001111,身份证 110101199001011234,卡号 6222020200112233", mapping)
    assert text == "手机 [PHONE_1],身份证 [ID_CARD_1],卡号 [CARD_1]"
    assert mapping == {
        "[PHONE_1]": "13800001111",
        "[ID_CARD_1]": "110101199001011234",
        "[CARD_1]": "6222020200112233",
    }


def test_id_card_takes_priority_over_card_pattern():
    """18 位证件号不得被 16-19 位卡号规则截获。"""
    mapping: dict[str, str] = {}
    text = mask_text("110101199001011234", mapping)
    assert text == "[ID_CARD_1]"


def test_same_value_reuses_placeholder():
    mapping: dict[str, str] = {}
    text = mask_text("从 13800001111 改为 13800001111", mapping)
    assert text == "从 [PHONE_1] 改为 [PHONE_1]"


def test_numbering_continues_across_calls():
    """同一会话多次脱敏,编号递增不冲突(跨轮次稳定)。"""
    mapping: dict[str, str] = {}
    assert mask_text("13800001111", mapping) == "[PHONE_1]"
    assert mask_text("13900002222", mapping) == "[PHONE_2]"
    assert mask_text("回拨 13800001111", mapping) == "回拨 [PHONE_1]"


def test_mask_known_names():
    mapping: dict[str, str] = {}
    assert mask_text("我是张三", mapping) == "我是[NAME_1]"


def test_amounts_and_short_numbers_not_masked():
    mapping: dict[str, str] = {}
    text = "余额 12800.50 元,共 5 笔,2026-08 结单"
    assert mask_text(text, mapping) == text
    assert mapping == {}


def test_rehydrate_restores_real_values():
    mapping = {"[PHONE_1]": "13800001111", "[NAME_1]": "张三"}
    text = rehydrate("[NAME_1] 您好,手机号 [PHONE_1] 已更新。", mapping)
    assert text == "张三 您好,手机号 13800001111 已更新。"


def test_rehydrate_keeps_unknown_placeholder():
    assert rehydrate("看到 [PHONE_9]", {}) == "看到 [PHONE_9]"


def test_mask_does_not_remask_placeholders():
    """占位符本身不含可命中规则的数字串,二次脱敏幂等。"""
    mapping: dict[str, str] = {}
    once = mask_text("13800001111", mapping)
    assert mask_text(once, mapping) == once
