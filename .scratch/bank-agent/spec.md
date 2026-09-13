# Spec: 工业级银行多智能体客服系统(LangGraph + Mock 银行核心 + 教学视频教案)

Status: ready-for-agent

## Problem Statement

项目作者是一名有 LangGraph 经验的工程师,需要一套**完整、工业级、可运行**的银行多智能体客服系统,用作教学视频的录制素材。
系统以 `docs/design-graph.png` 为设计原型:User Interface → Edge Layer(WAF/DDoS/限流/API 网关)→ 认证 → API → Coordinator Agent → Accounts/Transaction/Service 三个领域子 Agent → 各自的 MCP Server → 银行核心能力(余额查询、交易明细、结单请求、改地址、支票簿申请、KYC 更新),横向包含 PII 脱敏、授权、可观测性、成本追踪、评测套件、Session Store、第三方 LLM。
作者没有真实银行系统,所有下游对接均为 mock,但 mock 必须有真实的领域形状(仓储层、领域边界、写操作真实持久化),以便演示"将来接真系统时替换哪一层"。
除代码外,还需要一份独立的教案(`docs/teaching/`),即录制教学视频的分集话术与流程脚本,与项目代码分离维护。

## Solution

从零构建一个多智能体银行客服系统:

- 用户通过 CLI 或 HTTP API 与系统对话;FastAPI 对外暴露接口,前置 Edge 中间件栈(请求 ID、访问日志、限流、Bearer 校验)。
- 认证由 mock IdP(本地密钥签发 JWT)承担;token 经由 LangGraph 的 config/context 通道传递到工具调用层,**绝不进入 prompt 或 LLM 可见的工具参数**;MCP 侧按 scope 做授权校验。
- Coordinator Agent 做结构化路由(目标领域子 Agent 或 `clarify` 反问澄清),三个领域子 Agent 各为一个完整的 ReAct 循环子图,各自只挂载自己领域的 MCP 工具。
- 三个 FastMCP Server(Streamable HTTP,独立进程)背后是一个 mock 银行核心:SQLModel + SQLite 仓储层 + 种子数据,写操作(改地址、支票簿、KYC)真实落库。
- 会话状态用 SQLite checkpointer 持久化,支持断线续聊;多智能体共享状态有明确的写者与 reducer 规则。
- PII 在入站时用确定性规则脱敏为占位符,出站时按会话内映射回填。
- 可观测性与成本追踪用自托管 Langfuse(docker compose 一键起),LangGraph 通过 callback 接入。
- 评测套件:~40 条数据集,路由与工具调用用确定性断言,话术质量用 LLM-as-judge。

教案产出为 `docs/teaching/` 下 10 篇分集 markdown(E0–E9),每篇对应一个 git tag,包含开场话术、概念要点、演示步骤、收尾钩子。

## User Stories

### 银行客户(终端用户)

1. As a 银行客户, I want 通过对话查询我的账户余额, so that 我不用打客服电话。
2. As a 银行客户, I want 查询某笔交易的明细, so that 我能核对消费记录。
3. As a 银行客户, I want 申请账户结单(statement), so that 我能拿到正式的交易凭证。
4. As a 银行客户, I want 通过对话修改我的联系地址, so that 我不用跑网点。
5. As a 银行客户, I want 申请新的支票簿, so that 旧支票簿用完后能继续使用。
6. As a 银行客户, I want 提交/更新我的 KYC 资料, so that 我的账户保持合规状态。
7. As a 银行客户, I want 一次对话里先查余额再改地址, so that 我能连续办理多件事而不用重复登录。
8. As a 银行客户, I want 我说的话含糊时系统反问我澄清而不是瞎猜, so that 我不会被带到错误的业务里去。
9. As a 银行客户, I want 网络断开后重新进来还能接着上次的话题聊, so that 我不用从头解释。
10. As a 银行客户, I want 系统记得我跨会话的偏好(如常用账户), so that 体验更顺畅。
11. As a 银行客户, I want 我报出的手机号/卡号不原样发给第三方 LLM, so that 我的隐私得到保护。
12. As a 银行客户, I want 系统给我的回复里看到的还是我真实的号码而不是占位符, so that 脱敏对我透明。
13. As a 银行客户, I want 我只能操作我自己的账户, so that 我的资产安全。
14. As a 银行客户, I want 系统故障时得到一句得体的降级话术而不是报错堆栈, so that 体验可接受。

### 平台工程师/运营

15. As a 平台工程师, I want 每个请求带 request ID 并记访问日志, so that 我能串起一次调用的全链路。
16. As a 平台工程师, I want API 有限流, so that 单个用户刷爆后端的风险被控制。
17. As a 平台工程师, I want 所有 prompt、工具调用、Agent 决策都有 trace, so that 路由出错时我能定位是哪一步的问题。
18. As a 平台工程师, I want 成本按 model / Agent / 会话归因, so that 我知道钱花在哪。
19. As a 平台工程师, I want 改了 prompt 或路由逻辑后能跑评测回归, so that 我敢改系统。
20. As a 平台工程师, I want 未认证请求被 401、越权操作被 403, so that 安全边界清晰。
21. As a 平台工程师, I want token 不出现在任何 LLM 输入里, so that prompt 注入无法窃取凭证。
22. As a 平台工程师, I want 恶意/异常的工具调用被 MCP 侧 scope 校验拦下, so that 即使 LLM 被诱导也动不了越权数据。
23. As a 平台工程师, I want 一个命令拉起全部进程(API + 3 个 MCP Server + Langfuse), so that 本地演示不费劲。

### 讲师(项目作者)

24. As a 讲师, I want 每一集视频对应一个 git tag 和一篇教案, so that 我可以录一集发一集。
25. As a 讲师, I want 每集以一个工业级痛点开场(而不是以技术名词开场), so that 观众有代入感。
26. As a 讲师, I want E1 能现场演示单 Agent 挂满工具后的失败, so that 拆分的必要性不言而喻。
27. As a 讲师, I want 评测套件能现场对比改 prompt 前后的跑分, so that "你敢改 prompt 吗"有实证。
28. As a 讲师, I want trace 里能现场调试一次路由错误, so that 可观测性的价值可视。
29. As a 讲师, I want 收官集能明确指出接真银行系统时替换哪几个模块, so that 观众知道这套东西不是玩具。

### 学员(视频观众/仓库读者)

30. As a 学员, I want clone 仓库后照 `.env.example` 填 key 就能跑起来, so that 学习门槛最低。
31. As a 学员, I want 能 checkout 任意里程碑 tag 对照当集视频, so that 我可以从中间任意点切入。
32. As a 学员, I want 测试套件本地全绿且不消耗真实 API 额度, so that 我能放心改代码做实验。
33. As a 学员, I want 教案里讲清楚"WAF/DDoS 这类能力为什么在基础设施层而不是代码里", so that 我不对安全边界产生误解。

## Implementation Decisions

### 技术选型(已锁定)

- 语言/运行时:Python 3.12,已有 `.venv`;依赖管理用 pyproject。
- 编排:LangGraph,**手写 `StateGraph`**,不用 `langgraph-supervisor` 等封装库(supervisor/handoff 机制透明可见是教学核心)。
- LLM:DeepSeek,经 OpenAI 兼容客户端(如 `langchain-openai` 的 `ChatOpenAI` 配 `base_url`)接入;配置来自 `.env` 的 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`;provider 抽象保持很薄,直接依赖 LangChain chat model 接口。
- MCP:三个 FastMCP Server,**Streamable HTTP** 传输,独立进程独立端口;Agent 侧用 MCP client 远程调用;本地开发用单一脚本(如 honcho/Makefile)拉起全部进程。
- mock 银行核心:SQLModel + SQLite(独立库文件)+ 种子数据脚本;仓储层按领域切分,三个 MCP Server 各自只能访问自己领域的操作。
- 会话持久化:LangGraph SQLite checkpointer,thread_id = 会话 ID。
- 可观测性/成本:**自托管 Langfuse**(MIT,docker compose;Postgres + ClickHouse + Redis),经 `langfuse-langchain` callback 接入 LangGraph;成本用 Langfuse 原生能力,价格表填 DeepSeek 单价;Agent 维度归因用 trace metadata/tag。不自建成本计数器。
- 评测:自研离线跑分脚本 + 数据集文件;CI 中只跑确定性子集(用假 model)。
- 限流:FastAPI 中间件(slowapi 或等价物)。
- 认证:mock IdP 用固定密钥签 JWT;FastAPI 验签;授权按 scope。
- 前端:不做。入口 = CLI 聊天循环 + FastAPI HTTP 接口;可视化调试用 LangGraph Studio。

### 模块划分

- **Edge/API 层**:FastAPI 应用 + 中间件栈(请求 ID、访问日志、限流、Bearer 验签),挂载图调用;README/教案中明确说明 WAF/DDoS 属基础设施层,代码不假装实现。
- **Mock IdP**:签发带 scope 的 JWT 的最小服务/脚本。
- **Coordinator**:路由节点,LLM 输出结构化路由决策;`Command` 跳转到领域子图或 `clarify`。
- **三个领域子图**(accounts / transactions / service):各自完整 ReAct 循环,独立 system prompt,独立 MCP 工具集,推理完成后返回 Coordinator。
- **MCP 客户端层**:封装 MCP 连接与工具发现,供子图使用;token 从 config/context 注入到此层。
- **三个 FastMCP Server**:暴露各自领域的工具;每个工具调用执行 scope 校验;背后调用 mock 银行核心仓储层。
- **mock 银行核心**:SQLModel 实体 Customer / Account / Transaction / ServiceRequest(覆盖改地址、支票簿、KYC 三类服务请求)+ 仓储 + 种子数据。
- **PII 组件**:入站脱敏(确定性规则:手机号、身份证、卡号、姓名映射表)+ 会话内映射表 + 出站回填。
- **记忆组件**:会话内消息修剪/摘要;跨会话长期记忆用 LangGraph store。
- **评测组件**:数据集 + 确定性断言 + LLM-as-judge + 跑分报告。
- **教案**:`docs/teaching/` 下 E0–E9 十篇 markdown。

### 图架构与状态模型

- Coordinator 只做路由与汇总,不直接回答业务问题;`clarify` 是一等路由目标(意图不明时直接反问,不进子图)。
- 路由决策为结构化输出,形状:{ target: "accounts" | "transactions" | "service" | "clarify", rationale }。
- 子图异常由 Coordinator 捕获,给用户降级话术并记录 trace;路由只允许 Coordinator↔子 Agent 一跳往返,设最大步数兜底防循环。
- 多智能体共享状态:state schema 中共享键有唯一写者与 reducer 规则;子图私有键不泄漏到其他子图。
- token 传递通道:FastAPI 验签后把 token/用户信息放入 LangGraph 调用的 config(context),工具层从 config 读取;LLM 可见的 prompt 与工具参数中绝不出现 token。
- 会话内记忆:消息历史超阈值时做修剪/摘要;跨会话记忆(store)在会话开始时有选择地注入 prompt。

### PII 策略

- 确定性正则/规则脱敏,不用 Presidio/NER(银行场景 PII 格式高度规则化);NER 方案仅在教案中提及。
- 入站:用户消息进入图之前替换为 `[PHONE_1]` 式占位符,映射表存会话 state。
- 出站:最终回复按映射表回填;工具入参如需真实值,在工具层(不经 LLM)从映射还原。

### 里程碑(与视频分集一一对应,每个里程碑一个 git tag)

- **E0(tag `e0`)**:项目骨架——pyproject、ruff、pytest、配置加载(`.env`)、目录结构、docker compose(Langfuse占位,可后置)。视频内容:客户需求开场,不讲成品。
- **E1(tag `e1`)**:单 Agent + 全量工具的天真实现,可现场演示工具过多导致的失败(选错工具、上下文膨胀)。
- **E2(tag `e2`)**:垂直拆分为三个领域子图 + 三个 MCP Server + Coordinator 路由;协调者边界、clarify、异常降级、防循环。
- **E3(tag `e3`)**:mock IdP + JWT 验签 + scope 授权;token 走 config 通道;MCP 侧校验。
- **E4(tag `e4`)**:SQLite checkpointer、断线续聊、多智能体共享状态的写者/reducer 设计。
- **E5(tag `e5`)**:记忆管理——会话内修剪/摘要 + 跨会话长期记忆(store)。
- **E6(tag `e6`)**:PII 入站脱敏 + 出站回填。
- **E7(tag `e7`)**:Langfuse 接入,trace 调试演示,成本归因。
- **E8(tag `e8`)**:评测套件,改 prompt 前后跑分对比。
- **E9(tag `e9`)**:Edge 中间件栈收尾、上线清单、"接真银行系统替换哪几行"收尾讲解。

实施顺序按 E0→E9;每个里程碑产出可运行代码 + 对应 `docs/teaching/EN-*.md` 教案 + git tag。

## Testing Decisions

好测试的标准:只测外部可观察行为,不测实现细节(不断言 prompt 文本、不断言内部函数调用);测试不依赖真实 LLM、不消耗 API 额度、本地确定性全绿。

三条测试接缝(优先复用,不新增):

1. **最高接缝:FastAPI HTTP 层端到端**。在组合根(composition root)注入确定性假 chat model(预录的结构化路由决策与工具调用序列),经 HTTP 驱动完整图:认证 → 路由 → 子图 → MCP → mock 银行 → 响应。覆盖:多轮对话、澄清反问、断线续聊、越权 403、降级话术。
2. **工具/仓储接缝:MCP Server 工具与 mock 银行核心**。对种子 SQLite 库直接断言工具的输入输出与写操作落库结果(改地址后再查确实变了);scope 校验的拒绝路径在此层测。
3. **真实 LLM 不进测试套件**。DeepSeek 只用于离线评测脚本(E8)与手动演示;CI 跑 1+2 两层。

Prior art:无(greenfield,本 spec 建立首批测试与接缝约定)。

## Out of Scope

- 真实银行系统对接(所有下游为 mock,但按可替换的形状设计)。
- 任何形式的前端 UI。
- 真 WAF / DDoS 防护(基础设施层能力,代码中不实现,仅教案讲解)。
- 生产级部署(K8s、CI/CD 流水线、云上 Langfuse 高可用)。
- Postgres 等生产数据库(SQLite 足够;教案说明替换点)。
- NER/Presidio 等非规则 PII 识别。
- LangSmith(明确不用:闭源 SaaS、国内访问不稳;选自托管 Langfuse)。
- 多模态、语音、人工客服转接。
- `langgraph-supervisor` 等高层封装库(手写机制是教学目标)。

## Further Notes

- 本 spec 是"最终共识"的固化:经完整拷问式需求澄清(grilling)得出,所有标注"已锁定"的选型不要重开;若实施中发现必须变更,记录在对应 issue 的 Comments 中并说明理由。
- 教案与代码是两类产物:`docs/teaching/` 是视频话术与流程(中文),项目自身文档(README 等)面向工程读者。
- 分集的因果链:E1 制造问题 → E2 的拆分制造协调问题 → E2 的多 Agent 架构制造 token 传递(E3)与状态一致性(E4)问题 → 能跑之后是数据安全(E6)→ 可观测(E7)→ 可度量(E8)→ 可上线(E9)。规划时不要打乱这个叙事依赖。
- 新会话实施时:先读本 spec 与 `docs/design-graph.png`,再按里程碑在 `.scratch/bank-agent/issues/` 下拆 implementation issues(编号从 01,一票一文件),按 issue tracker 约定推进。
- `.env` 已存在且含真实 key,绝不可入库(`.gitignore` 已排除);学员用 `.env.example`。

## Comments
