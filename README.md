# bank-agent-learn

工业级银行多智能体客服系统(教学项目):Coordinator 结构化路由 + 三领域子图(accounts / transactions / service)+ 三个 FastMCP Server + mock 银行核心(SQLModel + SQLite,写操作真实落库)。

## 快速开始

```bash
make setup                 # 建 .venv 并安装依赖
cp .env.example .env       # 填入 LLM_API_KEY(DeepSeek 等 OpenAI 兼容接口)
make run                   # 种子数据 + 一键拉起 API + 3 个 MCP Server
```

另开一个终端,先向 mock IdP 取 token,再带 token 体验对话:

```bash
TOKEN=$(python -m bank_agent.auth.idp C001)   # 演示客户 C001,全量 scope
curl -s http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message": "帮我查一下余额"}'
```

也可以用 CLI 直接对话(需要先 `make run` 起 MCP Server;CLI 内部现场签发 token,与 HTTP 同一套认证契约):

```bash
make cli
```

## 测试

```bash
make test    # 全部本地确定性运行,不依赖真实 LLM、不消耗 API 额度
make lint
```

## 架构

```
用户(CLI / HTTP)
  → FastAPI(/chat,Bearer 验签:无 token 401、无业务 scope 403)
  → Coordinator(结构化路由 {target, rationale};clarify 是一等目标)
  → 领域子图(完整 ReAct 循环,独立 prompt 与工具集)
  → MCP Server(Streamable HTTP,独立进程独立端口;每个工具调用验签 + scope 校验)
  → mock 银行核心(仓储层按领域切分;接真系统时替换这一层)
```

安全与隐私边界:

- **token 通道**:mock IdP(本地固定密钥)签发带 scope 的 JWT。
  FastAPI 验签后经 LangGraph config 传到工具层,绝不进入 prompt 或 LLM 可见的工具参数。
- **授权**:每个工具声明所需 scope(`auth/scopes.py`),Agent 侧与 MCP 侧双层校验。
  customer_id 只来自 token,用户无法操作他人账户。
- **PII 脱敏**:入站用户消息按确定性规则(手机号/身份证/卡号 + 姓名映射表)替换为 `[PHONE_1]` 式占位符,映射存会话 state。
  工具入参在工具层还原真实值,工具结果脱敏后才给 LLM。
  最终回复按映射回填,对用户透明。

## 目录

- `src/bank_agent/graph/` — Coordinator、子图、图构建
- `src/bank_agent/mcp_servers/` — 三个 FastMCP Server
- `src/bank_agent/core/` — SQLModel 实体、仓储、种子数据
- `src/bank_agent/auth/` — JWT 签发/验签、scope 表、mock IdP CLI
- `src/bank_agent/pii.py` — PII 脱敏与回填
- `src/bank_agent/tool_providers.py` — Agent 侧工具接缝(远程 MCP / 进程内直连)
- `src/bank_agent/composition.py` — 组合根(生产 / 测试 wiring 的唯一入口)
- `docs/teaching/` — 教学视频分集教案(与代码分离维护)

## 说明

- Langfuse 为平台化阶段(E7)能力,`docker-compose.yml` 中仅占位,本阶段不需要任何 key。
- WAF/DDoS 属基础设施层能力,代码不假装实现,教案中讲解。
- 旧库文件没有 C002 种子客户:删除 `bank.sqlite3` 后重新 `make run` 即可。
