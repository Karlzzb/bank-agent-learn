# bank-agent-learn

工业级银行多智能体客服系统(教学项目):Coordinator 结构化路由 + 三领域子图(accounts / transactions / service)+ 三个 FastMCP Server + mock 银行核心(SQLModel + SQLite,写操作真实落库)。

## 快速开始

```bash
make setup                 # 建 .venv 并安装依赖
cp .env.example .env       # 填入 LLM_API_KEY(DeepSeek 等 OpenAI 兼容接口)
make run                   # 种子数据 + 一键拉起 API + 3 个 MCP Server
```

另开一个终端体验对话:

```bash
curl -s http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "帮我查一下余额"}'
```

也可以用 CLI 直接对话(需要先 `make run` 起 MCP Server):

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
  → FastAPI(/chat,认证 E3 补)
  → Coordinator(结构化路由 {target, rationale};clarify 是一等目标)
  → 领域子图(完整 ReAct 循环,独立 prompt 与工具集)
  → MCP Server(Streamable HTTP,独立进程独立端口)
  → mock 银行核心(仓储层按领域切分;接真系统时替换这一层)
```

- `src/bank_agent/graph/` — Coordinator、子图、图构建
- `src/bank_agent/mcp_servers/` — 三个 FastMCP Server
- `src/bank_agent/core/` — SQLModel 实体、仓储、种子数据
- `src/bank_agent/tool_providers.py` — Agent 侧工具接缝(远程 MCP / 进程内直连)
- `src/bank_agent/composition.py` — 组合根(生产 / 测试 wiring 的唯一入口)
- `docs/teaching/` — 教学视频分集教案(与代码分离维护)

## 说明

- Langfuse 为平台化阶段(E7)能力,`docker-compose.yml` 中仅占位,本阶段不需要任何 key。
- WAF/DDoS 属基础设施层能力,代码不假装实现,教案中讲解。
