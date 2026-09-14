# 上线清单与真实银行对接指南

本文回答两个问题:这套系统距离"上线"还差什么;接真实银行系统时替换哪几个模块。
WAF/DDoS 等基础设施能力也在此说明——它们不属于代码,代码不假装实现。

## 上线清单

### 认证与授权

- [ ] mock IdP(`auth/idp.py`,本地固定密钥签 JWT)替换为真实 IdP(OIDC)。
  `auth/tokens.py` 的验签改为校验 IdP 公钥(JWKS),`JWT_SECRET` 退役。
- [ ] scope 表(`auth/scopes.py`)与真实权限模型对齐,token TTL 按生产策略收紧。

### Edge / 基础设施

- [ ] 限流阈值(`RATE_LIMIT_PER_MINUTE`)按容量评估调整,限流状态外置到 Redis(当前为进程内内存,多实例部署时各实例独立计数)。
- [ ] WAF、DDoS 防护、TLS 终止:基础设施层能力(云 WAF / API 网关 / LB),由平台提供,不在应用代码内实现。
  应用层已做的:认证、授权、限流、请求 ID、访问日志。
- [ ] 访问日志(logger `bank_agent.access`)接入日志采集(如 Loki/ELK),按 X-Request-ID 串联。
- [ ] `docker-compose.yml` 中所有 `# CHANGEME` 占位密钥替换为真实密钥,`ENCRYPTION_KEY` 用 `openssl rand -hex 32` 生成。

### 数据

- [ ] SQLite 替换为生产数据库:`core/db.py` 的 `make_engine` 改连接串即可,仓储层(`core/repositories.py`)不变。
  涉及三处库文件:`BANK_DB_PATH`(业务)、`CHECKPOINT_DB_PATH`(会话)、`MEMORY_STORE_PATH`(长期记忆);
  LangGraph checkpointer/store 换用 Postgres 实现(`langgraph-checkpoint-postgres`)。
- [ ] 种子数据脚本(`core/seed.py`)仅用于演示,生产中删除。

### 可观测性与评测

- [ ] Langfuse 从本地 compose 换成高可用部署(或云服务),`.env` 换对应项目的 key。
- [ ] 模型价格表:Langfuse 默认价格表不含 DeepSeek,本地已用 `make langfuse-prices` 写入;
  换实例后需重跑;换其他模型在 Langfuse Models 页补单价,否则成本列为空。
- [ ] 每次改 prompt / 路由逻辑后跑评测回归:`python -m evals.run --real --tag <标签>`,与基线报告 `python -m evals.compare` 对比。

### LLM

- [ ] `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` 换生产供应商;key 走密钥管理,不进 `.env` 文件入库。
- [ ] 降级话术(`prompts.py` 的 `DEGRADED_MESSAGE`)与客服运营口径确认。

## 接真实银行系统:替换哪几个模块

mock 按"可替换"的形状设计,替换点集中在三层,Agent 与图逻辑零改动:

| 模块 | 现在是 | 接真系统时换成 | 不变的部分 |
| --- | --- | --- | --- |
| `src/bank_agent/core/repositories.py` + `core/db.py` + `core/models.py` | SQLModel + SQLite 仓储,写操作落 SQLite | 调用真实银行核心 API 的客户端(保持同样的函数签名与返回结构) | 领域工具、MCP Server、Agent 全部不变 |
| `src/bank_agent/auth/idp.py` + `auth/tokens.py` | 本地密钥签/验 JWT | 真实 IdP(OIDC/JWKS 验签) | scope 校验、config 通道传 token 的机制不变 |
| `src/bank_agent/mcp_servers/`(三个) | 直接调进程内仓储 | 不变(MCP 契约不变),只换它们背后的仓储实现 | 工具的 schema、scope 声明不变 |

Agent 侧(`graph/`、`tool_providers.py`)、PII 组件、记忆组件、Edge 中间件都不依赖下游是 mock 还是真实,无需改动。
