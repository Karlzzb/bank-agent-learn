"""PII 脱敏:确定性规则,不用 Presidio/NER(银行场景 PII 格式高度规则化)。

边界约定:
- 入站:用户消息进图前替换为 [PHONE_1] 式占位符,映射表存会话 state。
- 出站:最终回复按映射表回填真实值,脱敏对用户透明。
- 工具层:LLM 给出的占位符入参在工具层(不经 LLM)还原为真实值;
  工具结果中的真实值在返回给 LLM 前脱敏并入映射表。

映射表结构:{占位符: 真实值},如 {"[PHONE_1]": "13800001111"}。
同一真实值在同一会话内复用同一占位符,保证 LLM 看到的指代一致。
"""

import re

# 姓名映射表:mock 阶段为静态表(接真系统时从客户主数据加载),与种子客户保持一致。
KNOWN_NAMES = ("张三", "李四")

# 顺序即优先级:身份证(18 位)先于卡号(16-19 位)、手机号(11 位),避免长串被短规则截获。
_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("ID_CARD", re.compile(r"\d{17}[\dXx]")),
    ("CARD", re.compile(r"\d{16,19}")),
    ("PHONE", re.compile(r"1[3-9]\d{9}")),
)

# 匹配任一已生成的占位符:会话作用域标记,不得泄漏到跨会话存储(如长期记忆)。
PLACEHOLDER_PATTERN = re.compile(r"\[(?:ID_CARD|CARD|PHONE|NAME)_\d+\]")


def contains_placeholder(text: str) -> bool:
    """文本中是否含 PII 占位符。"""
    return bool(PLACEHOLDER_PATTERN.search(text))


def _placeholder_for(kind: str, value: str, mapping: dict[str, str]) -> str:
    """取该真实值的占位符:已映射则复用,否则按类型递增编号新建。"""
    for placeholder, real in mapping.items():
        if real == value:
            return placeholder
    seq = sum(1 for p in mapping if p.startswith(f"[{kind}_")) + 1
    placeholder = f"[{kind}_{seq}]"
    mapping[placeholder] = value
    return placeholder


def mask_text(text: str, mapping: dict[str, str]) -> str:
    """把文本中的 PII 替换为占位符,新映射写入 mapping(原地扩展)。"""
    for kind, pattern in _PATTERNS:
        text = pattern.sub(lambda m, kind=kind: _placeholder_for(kind, m.group(0), mapping), text)
    for name in KNOWN_NAMES:
        if name in text:
            text = text.replace(name, _placeholder_for("NAME", name, mapping))
    return text


def rehydrate(text: str, mapping: dict[str, str]) -> str:
    """把文本中的占位符按映射表回填为真实值;未映射的占位符原样保留。"""
    for placeholder in sorted(mapping, key=len, reverse=True):
        text = text.replace(placeholder, mapping[placeholder])
    return text
