# 《最小可用 Agent》需求分析文档

> 版本：1.0
> 日期：2026-07-30
> 状态：需求边界已确认
> 面向对象：Vibe Coding 题目评审者与实现者

## 1. 产品定义

用 Python 从零实现一个本地 CLI Agent Runtime。它调用真实的 DeepSeek V4 API，自主决定直接回答或调用工具，能在有限循环内完成任务，并支持可恢复、互相隔离的多 session 对话。

本项目的重点不是做一个功能丰富的聊天产品，而是证明以下核心能力确实由项目自身完成：

- Agent loop；
- 工具注册、选择、校验与执行；
- 多轮 session、context 与压缩；
- 异常处理、trace 与可重复验收。

## 2. 已确认的产品决策

- 使用 Python、CLI、本地部署。
- 不使用现有 Agent 框架完成核心 Runtime。
- 默认模型为 `deepseek-v4-pro`，通过 OpenAI 兼容协议调用。
- thinking 模式开启。
- 原始 `reasoning_content` 只作为模型协议所需的内部上下文；不得展示给用户或写入普通日志。
- 对外仅提供简短、可审计的决策摘要。
- 工具为 `calculator`、mock `search`、`todo`。
- `todo` 数据按 session 隔离，并能跨进程重启恢复。
- 不接入测试框架，以可重复执行的测试用例或验收脚本证明功能。
- 竞品仅用于分析成熟能力，不得成为核心 Runtime 的依赖。

## 3. 用户与核心场景

### 3.1 目标用户

- **评审者：**希望快速确认项目是否真正实现 Agent 核心机制。
- **实现者：**需要清晰、可测试的范围，避免遗漏 session、context、异常与交付材料。

### 3.2 核心场景

1. 用户提出普通问题，Agent 不调用工具，直接回答。
2. 用户提出计算、搜索或待办请求，Agent 自主选择工具并根据结果回答。
3. 用户基于上一轮内容追问；追问既可能是纯对话，也可能再次触发工具。
4. 用户创建两个 session，交错对话和管理待办，两边状态互不污染。
5. CLI 退出并重新启动后，用户仍能恢复指定 session。
6. 对话过长触发基础压缩，压缩后仍能回答依赖历史的追问。
7. API、模型输出或工具出现异常时，Agent 有限退出并给出可理解结果。

## 4. 范围

### 4.1 P0：必须完成

- 单 Agent、文本 CLI、DeepSeek 真实 API。
- 有最大轮次的 Agent loop。
- 统一工具注册与参数 Schema。
- 三个指定工具及跨工具连续调用。
- session 创建、识别、恢复、隔离与本地持久化。
- 多轮上下文、基础压缩及工具调用对完整性。
- 异常分类、脱敏 trace、决策摘要。
- 完整测试用例和全部提交材料。

### 4.2 本次不做

- Web UI、用户注册与权限系统。
- 多 Agent、handoff、工作流编排或人工审批。
- 真实联网搜索、RAG、向量数据库。
- 跨 session 的用户级长期记忆。
- 云部署、分布式执行和生产级并发。
- 语音、多模态、流式 UI。
- 复杂语义压缩、自动评测平台和性能压测。

## 5. 竞品调研

以下结论基于截至 2026-07-30 的各项目官方文档。

| 参考对象 | 官方定位与成熟能力 | 对本项目的启发 |
|---|---|---|
| OpenAI Agents SDK | 以 Agent、工具、session、guardrail 和 tracing 为核心；Runner 明确定义“调用模型—执行工具—再次调用—最终输出”的循环和最大轮次异常。[官方概览](https://openai.github.io/openai-agents-python/)、[运行循环](https://openai.github.io/openai-agents-python/running_agents/) | 循环终止条件、session 与 trace 必须是一等需求，不能散落在演示代码中。 |
| LangGraph | 强调有状态、持久化和 durable execution；使用 thread ID 隔离短期记忆，并区分 thread 内状态和跨 thread 长期记忆。[官方概览](https://langchain-ai.github.io/langgraph/index.html)、[Memory](https://langchain-ai.github.io/langgraph/how-tos/persistence/) | 明确 session 边界；本项目只做 thread/session 级记忆，不扩张为用户级长期记忆。 |
| Pydantic AI | 强调类型与 Schema 校验、工具参数错误反馈、请求/工具调用上限、消息历史处理和可观测性。[官方概览](https://pydantic.dev/docs/ai/overview/)、[工具 Schema](https://pydantic.dev/docs/ai/tools-toolsets/tools/)、[消息历史](https://pydantic.dev/docs/ai/core-concepts/message-history/) | 工具 Schema 需要实际验证；context 压缩不能破坏 tool call 与 tool result 的配对；循环应有独立预算。 |
| AutoGen | AgentChat 提供有状态 Agent，支持保存/加载 Agent 或团队状态及显式终止条件。[Agent](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/agents.html)、[状态管理](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html) | “可恢复”需要通过退出、重启、继续追问来验收，而不是只检查是否写了文件。 |

### 5.1 调研结论

- **最小不等于只有 while 循环。** 可终止、可恢复、可观察、可验证才构成最小可用 Runtime。
- **session、业务状态、模型 context、trace 是四类不同信息。** 混在同一消息列表中最容易造成串话、泄露或压缩后丢状态。
- **上下文压缩的验收目标是保持任务连续性，** 不是单纯减少消息条数。
- **模型输出不可信。** 工具名、参数 JSON、Schema、工具结果和终止状态都需要明确校验。
- **模型非确定性决定了测试应验证行为和状态，** 不应依赖回答文本逐字一致。

## 6. DeepSeek API 基线

DeepSeek 的 Chat Completions API 是无状态的，多轮历史需要由客户端重新传入。[多轮对话说明](https://api-docs.deepseek.com/guides/multi_round_chat)

本项目采用以下基线：

- 模型 ID：`deepseek-v4-pro`；
- Base URL：`https://api.deepseek.com`；
- 协议：OpenAI Chat Completions 兼容格式；
- thinking：开启；
- 工具调用：使用 API 返回的 `tool_calls`；
- 模型密钥：从运行环境提供，不进入源码、session 或 trace。

DeepSeek 官方要求：thinking 模式发生工具调用时，相关 `reasoning_content` 必须随上下文传回后续 API 请求，否则可能返回 400。[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)、[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls)

因此，原始推理内容只能存在于受控的内部协议状态中；对用户和 trace 暴露的是独立的决策摘要，而不是原始思维链。

## 7. 功能需求

### 7.1 Agent loop 与模型交互

| ID | 优先级 | 需求与验收口径 |
|---|---|---|
| FR-01 | P0 | 每次用户输入启动一次 run；run 最终只能以“成功回答”或明确的失败/限制原因结束。 |
| FR-02 | P0 | 模型无工具调用且返回有效内容时，Agent 向用户输出最终答案并结束 run。 |
| FR-03 | P0 | 模型返回一个或多个工具调用时，Agent 执行合法调用、追加结果并继续循环，直至最终回答。 |
| FR-04 | P0 | 每个 run 必须受最大模型轮次约束；超限时停止，不再调用模型或工具，并显示“达到轮次上限”。具体默认值可配置且必须写入 README。 |
| FR-05 | P0 | 必须解析并区分 `content`、`tool_calls`、`reasoning_content` 与结束原因；空内容、畸形参数或未知结构不得被当作成功。 |
| FR-06 | P0 | 默认连接 `deepseek-v4-pro`；模型名、Base URL 和密钥由外部配置提供，其中模型与 Base URL 可有已声明的默认值，密钥不可有硬编码默认值。 |
| FR-07 | P0 | 原始 `reasoning_content` 不向用户输出、不进入普通 trace；如协议要求续传，只能作为内部 session 状态使用。 |
| FR-08 | P0 | 每一步对外产生简短决策摘要，只说明“直接回答、调用何种工具、继续或结束”及结果状态，不复述私有推理。 |

### 7.2 工具系统

| ID | 优先级 | 需求与验收口径 |
|---|---|---|
| FR-09 | P0 | 工具通过统一注册机制提供名称、描述、JSON 参数 Schema 和可执行入口；名称必须唯一。 |
| FR-10 | P0 | 传给模型的工具列表来自注册信息，不能为三个工具分别硬编码模型调用流程。 |
| FR-11 | P0 | 工具执行前校验工具是否存在、参数是否为合法 JSON、是否符合 Schema；非法调用不得直接进入执行入口。 |
| FR-12 | P0 | 工具返回统一的成功或失败结果；失败结果必须包含可理解的错误类型，不能伪装成正常数据。 |
| FR-13 | P0 | `calculator` 支持常见算术计算；非法表达式可控失败，且不得执行任意代码或系统命令。 |
| FR-14 | P0 | `search` 使用稳定的 mock 数据；输出必须明确标识为模拟结果，不能让用户误认为是实时搜索。 |
| FR-15 | P0 | `todo` 至少支持新增和查看；新增后可在同一 session 后续轮次与进程重启后查到。 |
| FR-16 | P0 | 同一次 run 可连续使用不同工具，例如先搜索再新增待办；最终答案应基于实际工具结果。 |
| FR-17 | P0 | 工具失败或模型重复调用时，不得造成无界循环；有副作用的待办操作不得因内部重试而静默重复。 |

### 7.3 Session 与持久化

| ID | 优先级 | 需求与验收口径 |
|---|---|---|
| FR-18 | P0 | 每个 session 有稳定且唯一的标识；用户可创建新 session、查看可恢复 session，并按标识继续对话。具体命令语法不在本文限定。 |
| FR-19 | P0 | 不同 session 的对话历史、摘要、内部模型状态和 todo 数据必须隔离。 |
| FR-20 | P0 | CLI 正常退出并重新启动后，指定 session 能继续对话，已有 todo 和必要上下文仍可用。 |
| FR-21 | P0 | 写入失败或 run 中途失败时，不得把 session 留在无法再次加载的状态；失败信息需可定位。 |
| FR-22 | P0 | 不允许仅依赖进程内存满足“可恢复”；必须用本地持久化状态完成重启验收。 |

### 7.4 Context 管理与压缩

| ID | 优先级 | 需求与验收口径 |
|---|---|---|
| FR-23 | P0 | 发送给模型的 context 至少能表达系统约束、必要历史、当前输入、完整的待处理工具调用及其结果。 |
| FR-24 | P0 | 普通多轮追问能引用前文；工具型追问能继续使用此前工具结果或 session 内业务状态。 |
| FR-25 | P0 | context 达到可配置阈值时触发基础压缩；阈值必须可降低，以便在录屏和测试中稳定演示。 |
| FR-26 | P0 | 压缩后仍保留关键用户事实、未完成意图、必要工具结论和近期对话；同一组 tool call 与 tool result 不得被拆散。 |
| FR-27 | P0 | 原始完整 session 记录与实际发送给模型的 context 应能区分；压缩不得删除独立存储的 todo 业务状态。 |
| FR-28 | P0 | 压缩成功或失败必须可观察；压缩失败时不得导致 session 损坏或无限重试。 |

### 7.5 Trace 与异常

| ID | 优先级 | 需求与验收口径 |
|---|---|---|
| FR-29 | P0 | 每次 run 可通过 run ID 与 session ID 追踪；至少记录步骤序号、动作类型、工具名、执行状态、耗时、错误类型与终止原因。 |
| FR-30 | P0 | trace 不得包含 API Key、原始 `reasoning_content`；工具参数或结果如含敏感字段，应可脱敏。 |
| FR-31 | P0 | 对 API 配置/鉴权、余额、限流、服务异常、模型输出异常、工具异常、存储异常、轮次超限分别给出可理解错误。 |
| FR-32 | P0 | 短暂服务故障可以有限恢复，但不得无限重试；失败后用户应知道任务未完成，session 仍可继续使用。 |
| FR-33 | P0 | 400/401/402/422 等不可通过原请求自动恢复的问题不得反复请求；429/500/503 等服务类错误也必须受重试上限约束。[DeepSeek 错误码](https://api-docs.deepseek.com/quick_start/error_codes/) |

## 8. 非功能需求

| ID | 需求 |
|---|---|
| NFR-01 | 核心 loop、工具调度、session、context 和 trace 不得依赖 LangGraph、OpenHands、OpenClaw、OpenAI Agents SDK、AutoGen、Pydantic AI 等 Agent 框架。 |
| NFR-02 | 项目必须能按 README 在本地从零配置和运行；Python 版本及全部依赖需明确声明。 |
| NFR-03 | 代码与提交材料不得包含真实 API Key、用户私有推理或未脱敏敏感数据。 |
| NFR-04 | 同一输入不要求逐字复现模型回答，但状态变化、工具选择范围、终止原因和错误类型必须可验证。 |
| NFR-05 | trace 应足以复盘一次 run，同时与面向用户的自然语言输出分离。 |
| NFR-06 | 本题不设性能 SLA；但模型调用次数、工具调用次数和总耗时应可从 trace 获取。 |

## 9. 测试与验收用例

不要求测试框架。每个用例须有前置条件、输入、预期行为、实际结果与通过/失败标记；涉及模型的用例按语义和状态验收，不比较固定文案。

| 用例 | 验收重点 |
|---|---|
| TC-01 直接回答 | 普通问题不调用工具，run 正常结束。 |
| TC-02 计算工具 | Agent 自主调用 `calculator`，结果正确并进入最终回答。 |
| TC-03 Mock 搜索 | Agent 调用 `search`，结果稳定且明确标识为 mock。 |
| TC-04 Todo 持久化 | 新增并查看待办；重启 CLI 后仍存在。 |
| TC-05 Session 隔离 | session A 与 B 保存不同对话和待办，交错恢复时不串话。 |
| TC-06 普通追问 | 追问省略前文主语，Agent 能根据同一 session 历史回答。 |
| TC-07 工具追问 | 追问基于前一工具结果，并按需再次调用工具。 |
| TC-08 多工具链 | 一次任务连续触发两种工具，最终回答引用真实执行结果。 |
| TC-09 非法参数 | 参数不符合 Schema 时不执行工具，run 可控结束或有限恢复。 |
| TC-10 未注册工具 | 未知工具不会被执行，trace 中有明确错误。 |
| TC-11 工具失败 | 工具异常不会使 CLI 崩溃或进入无限循环。 |
| TC-12 API 异常 | 缺失/错误密钥及可模拟服务错误都有明确提示，且不泄露密钥。 |
| TC-13 最大轮次 | 构造无法结束的响应，达到限制后停止并记录终止原因。 |
| TC-14 Context 压缩 | 降低阈值触发压缩；压缩后仍记得预设事实并能完成追问。 |
| TC-15 工具消息完整性 | 压缩或恢复后，tool call 与 tool result 保持配对，不触发协议错误。 |
| TC-16 推理隐私 | CLI、普通日志和 trace 中均不存在原始 `reasoning_content`。 |
| TC-17 Trace 完整性 | 一次工具 run 可由 session ID、run ID 和步骤记录完整复盘。 |

## 10. 录屏最小演示路径

录屏至少连续证明：

1. 启动项目并使用真实 DeepSeek API；
2. 直接回答；
3. calculator 工具调用；
4. mock search 后新增 todo 的多工具任务；
5. 创建两个 session 并证明 todo 隔离；
6. 退出、重启并恢复其中一个 session；
7. 触发 context 压缩后继续追问；
8. 展示一次异常和对应脱敏 trace。

## 11. 最终交付物

- 可运行的完整源码及代码链接；
- 终端操作录屏；
- README，至少包含：
  - 环境与运行方式；
  - DeepSeek API 配置；
  - 系统边界与核心 Runtime 说明；
  - session、context、压缩及 memory 的召回和放置时机；
  - 工具注册规范；
  - trace 与异常说明；
  - 测试用例执行方式；
- AI Prompt 与问题解决记录；
- 测试用例及结果；
- 本需求分析文档。

## 12. 完成定义

只有同时满足以下条件才算完成：

- 所有 P0 功能需求均有可运行证据；
- TC-01 至 TC-17 均执行、记录结果并通过；
- 核心 Runtime 未借用现成 Agent 框架；
- 使用 `deepseek-v4-pro` 真实 API 跑通直接回答、工具调用及多轮追问；
- session 隔离、跨进程恢复和 context 压缩通过验收；
- 原始推理和 API Key 未出现在用户输出、普通日志或提交内容中；
- 录屏、README、代码链接、Prompt/问题记录齐全，评审者能按 README 复现。

## 13. 最高风险

| 风险 | 必须守住的验收底线 |
|---|---|
| 核心流程实际由框架代劳 | 能明确指出并演示项目自身的 loop、调度、状态与解析逻辑。 |
| DeepSeek thinking 工具消息续传不完整 | 多轮工具对话与重启恢复不出现 400，tool call/result 保持完整。 |
| session 仅换了 ID，底层状态仍共享 | 对话、摘要、内部模型状态和 todo 均通过双 session 隔离用例。 |
| 压缩等同于粗暴截断 | 压缩后关键事实可追问，工具消息不失配，todo 不丢失。 |
| 模型异常导致死循环 | 最大轮次与错误终止在主流程中真实生效。 |
| mock 数据被包装成实时结果 | 所有 search 输出都清楚标识为模拟数据。 |
| trace 泄露密钥或私有推理 | 用例检查输出及日志，不出现 API Key 和原始 `reasoning_content`。 |
| 演示能跑但无法复现 | 全新环境可按 README 配置、运行和执行验收用例。 |
