"""Langfuse 价格表初始化:把 DeepSeek 单价写进自托管实例。

Langfuse 默认价格表不含 DeepSeek 模型(已核实 default-model-prices.json),
成本归因前必须先建模型定义,否则成本列为空。
经公开 API(Basic auth = public/secret key)创建;同名定义已存在则跳过,幂等可重复执行。

用法:python -m bank_agent.langfuse_setup(或 make langfuse-prices)
"""

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from bank_agent.config import Settings, get_settings

# DeepSeek 官方标价,USD/token(cache-miss 输入、输出;缓存命中折扣不细分,统一按 miss 计)
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27e-6, 1.10e-6),
    "deepseek-reasoner": (0.55e-6, 2.19e-6),
}


def model_payload(model: str) -> dict[str, Any]:
    """POST /api/public/models 的请求体:精确匹配模型名,按 token 计输入/输出单价。"""
    input_price, output_price = MODEL_PRICES[model]
    return {
        "modelName": model,
        "matchPattern": f"(?i)^({model})$",
        "unit": "TOKENS",
        "inputPrice": input_price,
        "outputPrice": output_price,
    }


def _http(settings: Settings, method: str, path: str, body: dict | None = None) -> Any:
    """Langfuse 公开 API 调用:Basic auth,public key 为用户名、secret key 为密码。"""
    url = f"{settings.langfuse_base_url.rstrip('/')}{path}"
    credentials = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def ensure_model_prices(settings: Settings, *, http=_http) -> str:
    """为 settings.llm_model 建价格定义(幂等);返回动作描述供打印。http 可注入以便测试。"""
    model = settings.llm_model
    if model not in MODEL_PRICES:
        return f"跳过:{model} 不在内置价格表,请在 Langfuse UI 的 Models 页手工补单价"
    existing = http(settings, "GET", "/api/public/models")
    if any(m.get("modelName") == model for m in existing.get("data", [])):
        return f"已存在:{model} 价格定义无需重复创建"
    http(settings, "POST", "/api/public/models", model_payload(model))
    input_price, output_price = MODEL_PRICES[model]
    return f"已创建:{model} 价格定义(输入 {input_price}/token,输出 {output_price}/token)"


def main() -> None:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        print("未配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY,无法初始化价格表")
        raise SystemExit(1)
    try:
        print(ensure_model_prices(settings))
    except urllib.error.URLError as exc:
        print(f"连不上 Langfuse({settings.langfuse_base_url}):{exc};先 make run 起栈再试")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
