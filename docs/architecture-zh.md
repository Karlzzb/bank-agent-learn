# 系统架构图(与代码一致)

本图按 `src/bank_agent/` 的实际实现绘制,替代英文设计原型 `design-graph.png`。
与原型的差异见文末对照说明。

```mermaid
flowchart TB
    subgraph 客户端
        UI["用户界面<br/>(CLI / HTTP 客户端)"]
    end

    subgraph Edge["Edge 层(FastAPI 中间件 edge.py)"]
        REQID["请求 ID<br/>X-Request-ID + 访问日志"]
        RL["按客户限流<br/>(/healthz 不限流)"]
    end

    WAF["WAF / DDoS<br/>(基础设施层,不在代码内)"]

    subgraph API["API 层(api.py)"]
        CHAT["POST /chat"]
        AUTH["认证:mock IdP JWT<br/>401/403 闸门"]
    end

    PIIIN["PII 入站脱敏<br/>(pii.py:手机号/卡号/身份证 → 占位符)"]

    subgraph Graph["LangGraph 图(graph/)"]
        CTX["manage_context<br/>会话内摘要压缩 + 长期记忆读取"]
        COORD["Coordinator<br/>结构化路由:accounts / transactions / service / clarify"]
        subgraph Agents["三个领域 ReAct 子图(带降级,MAX_TOOL_STEPS=5)"]
            AA["Accounts Agent"]
            TA["Transactions Agent"]
            SA["Service Agent"]
        end
    end

    PIIRE["工具层还原<br/>(tool_providers.py:占位符 → 真实值,LLM 不可见)"]

    subgraph MCP["三个 MCP Server(Streamable HTTP,X-Bank-Token 头,scope 双层校验)"]
        MA["accounts-mcp :8101<br/>query_balance"]
        MT["transactions-mcp :8102<br/>list_transactions / get_transaction_detail / request_statement"]
        MS["service-mcp :8103<br/>change_address / request_cheque_book / update_kyc"]
    end

    DB[("bank.sqlite3<br/>mock 银行核心")]
    CKPT[("checkpoints.sqlite3<br/>会话状态(thread_id)")]
    STORE[("memory.sqlite3<br/>跨会话长期记忆(profiles)")]
    LLM["第三方 LLM<br/>(DeepSeek,OpenAI 兼容接口)"]
    LF["自托管 Langfuse :3000<br/>trace / 三维归因 / 成本"]
    EVAL["评测套件 evals/<br/>(CI 零消耗 + --real)"]

    UI --> REQID --> RL --> CHAT
    WAF -.->|部署在网关侧| REQID
    CHAT --> AUTH --> PIIIN --> CTX --> COORD
    COORD --> AA & TA & SA
    AA & TA & SA --> PIIRE
    PIIRE --> MA & MT & MS
    MA & MT & MS --> DB
    CTX <--> CKPT
    CTX <--> STORE
    Graph -.->|CallbackHandler| LF
    COORD & Agents -.->|调用| LLM
    EVAL -.->|回归跑分| Graph

    style WAF stroke-dasharray: 5 5
```

## 与 `design-graph.png`(英文设计原型)的差异

原型是动工前的设计稿,实现后有以下出入:

| 原型中的元素 | 实际实现 |
| --- | --- |
| Edge 层含 WAF / DDoS / API Gateway | 代码内只有请求 ID、访问日志、按客户限流;WAF/DDoS 明确放在基础设施层(E9 论点) |
| Authentication = Bank's identity provider | mock IdP 自签 HS256 JWT;接真系统时换 OIDC/JWKS(`docs/go-live.md`) |
| Authorisation 挂在 Coordinator 旁 | 授权在 API 层(401/403)+ MCP 工具层 scope 校验;token 走 config 通道,不进 prompt |
| Observability 含 CPU / Memory / Disk | 无系统指标;只有 Langfuse trace(prompt、Agent 调用、工具调用、耗时) |
| 独立 Cost Tracker 组件 | 不建计数器;成本由 Langfuse 价格表在展示层查表得出 |
| Self Hosted LLM + Third-party LLM | 只用第三方 LLM(DeepSeek) |
| Session Store(单一) | 拆成两个:checkpointer(会话状态)+ store(跨会话长期记忆) |
| 无记忆与评测框 | 实际有会话内摘要压缩、长期记忆、PII 三道边界、评测套件 |
