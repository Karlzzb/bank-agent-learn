# bank-agent-learn

工业级银行多智能体客服系统(教学项目):Coordinator 结构化路由 + 三领域子图(accounts / transactions / service)+ 三个 FastMCP Server + mock 银行核心(SQLModel + SQLite,写操作真实落库)。

## 快速开始

```bash
make setup                 # 建 .venv 并安装依赖
cp .env.example .env       # 填入 LLM_API_KEY(DeepSeek 等 OpenAI 兼容接口)
make run                   # 种子数据 + 一键拉起 Langfuse + 3 个 MCP Server + API
```

`make run` 会先用 docker compose 拉起自托管 Langfuse(Postgres + ClickHouse + Redis + MinIO);
没有 docker 或 `LAUNCH_LANGFUSE=false` 时自动跳过,对话功能不受影响。

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
  → FastAPI(Edge 栈:请求 ID / 访问日志 / 限流;Bearer 验签:无 token 401、无业务 scope 403)
  → Coordinator(结构化路由 {target, rationale};clarify 是一等目标)
  → 领域子图(完整 ReAct 循环,独立 prompt 与工具集)
  → MCP Server(Streamable HTTP,独立进程独立端口;每个工具调用验签 + scope 校验)
  → mock 银行核心(仓储层按领域切分;接真系统时替换这一层,见 docs/go-live.md)
```

安全与隐私边界:

- **token 通道**:mock IdP(本地固定密钥)签发带 scope 的 JWT。
  FastAPI 验签后经 LangGraph config 传到工具层,绝不进入 prompt 或 LLM 可见的工具参数。
- **授权**:每个工具声明所需 scope(`auth/scopes.py`),Agent 侧与 MCP 侧双层校验。
  customer_id 只来自 token,用户无法操作他人账户。
- **PII 脱敏**:入站用户消息按确定性规则(手机号/身份证/卡号 + 姓名映射表)替换为 `[PHONE_1]` 式占位符,映射存会话 state。
  工具入参在工具层还原真实值,工具结果脱敏后才给 LLM。
  最终回复按映射回填,对用户透明。

会话与记忆:

- **断线续聊**:会话状态用 SQLite checkpointer 持久化(`CHECKPOINT_DB_PATH`),thread_id 即会话 ID。
  进程重启后凭同一 thread_id 续聊,上下文完整(CLI 退出时会打印会话 ID,`python -m bank_agent.cli <id>` 续聊)。
- **会话内摘要**:消息数超过 `HISTORY_MAX_MESSAGES` 后,最旧一段压缩为中文摘要,保留最近 `HISTORY_KEEP_RECENT` 条原文,长会话不丢关键上下文。
- **跨会话长期记忆**:用户说"记住/常用/默认…"时,LLM 提取偏好写入 LangGraph store(SQLite,按客户隔离);
  领域子图(真正办事的一层)执行时把已知偏好注入 prompt,含 PII 占位符的提取结果一律丢弃,store 不落 PII。

## 可观测性与成本(Langfuse)

自托管 Langfuse v3,`make run` 一键拉起;首次访问 http://localhost:3000 用 `demo@bank-agent.local` / `bank-agent-demo-password` 登录(组织、项目、API key 已由 compose 的 `LANGFUSE_INIT_*` 自动建好,与 `.env.example` 预填一致)。

- **trace**:LangGraph 经 `langfuse.langchain.CallbackHandler` 接入,一次对话的路由决策、LLM 调用、工具调用全在同一条 trace;路由出错能在 trace 里定位到哪一步。
- **归因维度**:会话 = `langfuse_session_id`(即 thread_id),用户 = `langfuse_user_id`(customer_id),
  领域 Agent = 子图 observation 的 `metadata.agent` 与节点名(coordinator / accounts / transactions / service)。
- **成本**:用 Langfuse 原生价格表,不自建计数器。
  Langfuse 默认价格表**不含** DeepSeek 模型,首次起栈后跑一次 `make langfuse-prices` 写入单价(幂等,经公开 API);
  换其他模型时在 Langfuse UI 的 Models 页补单价,之后按 model / Agent / 会话过滤即可看成本。
- 未配置 key 时接入整体关闭,系统照常运行(测试与离线场景零依赖)。

## 评测套件

```bash
python -m evals.run                    # CI 模式:确定性子集,假 model,零 API 消耗
python -m evals.run --real             # 全量 ~40 条:真实 LLM + LLM-as-judge(离线手动跑)
python -m evals.compare old.json new.json   # 对比两次跑分(改 prompt 前后回归)
```

- 数据集在 `evals/datasets/`:路由与工具调用用确定性断言(route / tool_calls / 回复包含 / 落库结果),话术质量用 LLM-as-judge。
- 每轮跑分产出 `evals/reports/<时间戳>-<git短sha>.{json,md}`,含 git 提交与 prompts 哈希,改 prompt 前后可对比。
- CI(`.github/workflows/ci.yml`)只跑确定性子集,不消耗真实 API 额度。

## Edge 与上线

- 每个请求带 `X-Request-ID` 响应头,访问日志(logger `bank_agent.access`)按它串联;
  `/chat` 按客户限流(`RATE_LIMIT_PER_MINUTE`,单用户刷爆后端被 429 拦下),`/healthz` 不限流。
- 上线清单、WAF/DDoS 为什么在基础设施层、接真银行系统替换哪几个模块:见 [docs/go-live.md](docs/go-live.md)。

## 目录

- `src/bank_agent/graph/` — Coordinator、子图、图构建
- `src/bank_agent/memory/` — SQLite checkpointer 装配、摘要/偏好节点、SqliteStore
- `src/bank_agent/mcp_servers/` — 三个 FastMCP Server
- `src/bank_agent/core/` — SQLModel 实体、仓储、种子数据
- `src/bank_agent/auth/` — JWT 签发/验签、scope 表、mock IdP CLI
- `src/bank_agent/pii.py` — PII 脱敏与回填
- `src/bank_agent/edge.py` — Edge 中间件栈(请求 ID、访问日志、限流)
- `src/bank_agent/observability.py` — Langfuse 接入与归因维度
- `src/bank_agent/tool_providers.py` — Agent 侧工具接缝(远程 MCP / 进程内直连)
- `src/bank_agent/composition.py` — 组合根(生产 / 测试 wiring 的唯一入口)
- `evals/` — 评测套件(数据集、runner、judge、跑分报告)
- `docs/go-live.md` — 上线清单与真实银行对接指南
- `docs/teaching/` — 教学视频分集教案(与代码分离维护)

## 说明

- WAF/DDoS 属基础设施层能力,代码不假装实现,见 docs/go-live.md。
- 旧库文件没有 C002 种子客户:删除 `bank.sqlite3` 后重新 `make run` 即可。
