# 教学视频分集教案(E0–E9)

本目录是配套教学视频的逐集教案,面向视频观众(中文口播),与项目代码分离维护。
项目自身的工程文档见根目录 README.md 与 docs/go-live.md。
每篇教案固定四段:**开场话术 → 概念要点 → 演示步骤 → 收尾钩子**。
每集以一个工业级痛点开场,而不是以技术名词开场。

## 分集地图

| 集 | 教案 | 一句话 | git tag |
| --- | --- | --- | --- |
| E0 | [E0-客户需求开场.md](E0-客户需求开场.md) | 客户到底要什么;设计图走读;全系列 roadmap | `e0` |
| E1 | [E1-单Agent挂满工具的失败.md](E1-单Agent挂满工具的失败.md) | 最直觉的做法现场翻车:一个 Agent 挂 7 个工具 | `e1` |
| E2 | [E2-垂直拆分多智能体.md](E2-垂直拆分多智能体.md) | Coordinator 路由 + 三领域子图 + 三个 MCP Server | `e2` |
| E3 | [E3-认证与授权.md](E3-认证与授权.md) | token 走 config 通道,LLM 永远碰不到凭证 | `e3` |
| E4 | [E4-会话持久化.md](E4-会话持久化.md) | 断线续聊;共享状态的写者与 reducer 规则 | `e4` |
| E5 | [E5-记忆管理.md](E5-记忆管理.md) | 会话内摘要压缩 + 跨会话长期偏好 | `e5` |
| E6 | [E6-PII脱敏.md](E6-PII脱敏.md) | 手机号/卡号不原样发给第三方 LLM | `e6` |
| E7 | [E7-可观测性与成本.md](E7-可观测性与成本.md) | trace 里现场调试一次路由错误 | `e7` |
| E8 | [E8-评测套件.md](E8-评测套件.md) | 改 prompt 前后跑分对比,"你敢改吗"有实证 | `e8` |
| E9 | [E9-Edge收尾与接真银行系统.md](E9-Edge收尾与接真银行系统.md) | 上线清单;WAF/DDoS 为什么在基础设施层;收官 | `e9` |

分集叙事链(不可打乱):E1 制造问题 → E2 的拆分制造协调问题 → 多 Agent 架构制造 token 传递(E3)与状态一致性(E4/E5)问题 → 能跑之后是数据安全(E6)→ 可观测(E7)→ 可度量(E8)→ 可上线(E9)。

## tag 与 commit 对照(含实施压缩说明)

本仓库按 4 个功能 PR 交付,里程碑被压缩在少量 commit 上,因此部分 tag 指向同一 commit。
tag 语义是"看完第 N 集时,系统应该具备的全部能力",按此原则取**单调包含**的 commit:

| tag | commit | 说明 |
| --- | --- | --- |
| `e0` | 8c488e9 | 立项:设计图、.env 模板、文档骨架;尚无可运行代码,配合"不讲成品"的开场 |
| `e1` | be36224 | 与 e2 同 commit;MCP 工具已可用,天真单 Agent 用 docs/teaching/assets/naive_agent.py 现场重建 |
| `e2` | be36224 | Coordinator + 三领域子图 + 三个 MCP Server + mock 银行核心 |
| `e3` | eb25bc1 | 认证授权;PII 代码也在此 commit 并入(E6 主题,见该集教案说明) |
| `e4` | 8036ed5 | 会话持久化(e5/e6 同 commit) |
| `e5` | 8036ed5 | 记忆管理 |
| `e6` | 8036ed5 | PII 脱敏(代码在 e3 commit 已并入) |
| `e7` | fb5498c | Langfuse 可观测与成本(e8 同 commit) |
| `e8` | fb5498c | 评测套件 |
| `e9` | 教案收官 commit(main 最新) | Edge 栈在 fb5498c 已就绪,收官集含全部教案 |

学员用法:`git checkout e<N>` 对照当集视频;教案本身始终在 main 上维护,旧 tag 里没有教案目录。
跨 tag 拷贝教案脚本:`git show main:docs/teaching/assets/naive_agent.py > naive_agent.py`。

## 演示通用约定

- 演示客户:C001 张三(全量业务数据)、C002 李四(越权/隔离演示)。
- 起栈:`make run`(种子数据 + Langfuse + 3 个 MCP Server + API;无 docker 时自动跳过 Langfuse)。
- 取 token:`TOKEN=$(python -m bank_agent.auth.idp C001)`。
- 各集演示步骤里出现的命令都在对应 tag 下核对过;凡涉及跨 tag 差异(如 e2 尚无认证),教案内有显式提示。
- 真实 LLM 调用只出现在必要演示里;`make test` 与 `python -m evals.run`(CI 模式)零 API 消耗。
