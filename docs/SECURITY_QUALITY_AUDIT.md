# MVP 安全与质量审查

> 审查日期：2026-07-31
> 审查角色：安全审查员 + 质量工程师
> 审查范围：只检查异常路径、权限边界、输入校验、失败体验、测试覆盖和 `TASK.md` 完成度；本次不增加功能、不修改生产运行逻辑。

> 整改复核：2026-07-31。下文第 1～7 节保留整改前的审查快照和原始证据；当前状态以本节复核表为准。

## 0. P0 整改复核

| ID | 状态 | 落地结果 | 回归证据 |
|---|---|---|---|
| P0-01 | 已完成 | 新 run 前恢复同 session 的遗留 `running` run，统一标记 `failed/interrupted`、`context_valid=0`。 | TC-18 覆盖 user-only、assistant tool call 后、tool result 后三个中断点。 |
| P0-02 | 已完成 | `ToolContext` 移除原始 connection；todo 仅获得 session-bound `SessionTodoStore`；run/message/trace repository 校验 session/run 归属。 | TC-19 验证普通工具无数据库能力和跨 session run 读写失败。 |
| P0-03 | 已完成 | system prompt 保持固定；滚动摘要作为明确标注的非可信 `user` memory 消息。 | TC-14 将越权文字压入摘要，并断言其不会进入 system prompt。 |
| P0-04 | 已完成 | 增加用户输入、hard context、每响应/每 run 工具数、工具参数、模型输出 token/字符与 HTTP 响应字节硬预算。 | TC-20 验证输入、context、两级工具数、参数、模型字符、HTTP 响应和 `max_tokens`。 |
| P0-05 | 已完成 | 最后一个模型步骤返回工具调用时不保存调用、不执行工具，直接 `max_steps`。 | TC-13 验证最后一步无工具执行事件。 |
| P0-06 | 已完成 | 默认仅允许 DeepSeek 官方 HTTPS 主机；自定义主机必须显式启用且仍强制 HTTPS、无 URL 凭据/query/fragment。 | TC-19 验证 HTTP 与未授权自定义主机被拒绝。 |
| P0-07 | 已完成 | 工具 trace 不再保存参数和结果正文，仅记录名称、call ID 短哈希、字符数与状态；模型 usage 只保留数值 token 白名单。 | TC-19 验证工具正文和非白名单 usage 中的自由文本秘密不进入 trace。 |
| P0-08 | 已完成 | 仅接受无工具的 `stop` 和有工具的 `tool_calls`；`length` 分类为 `model_output_truncated`。 | TC-20 验证部分答案不会被标记成功。 |
| P0-09 | 已完成 | 应用创建目录收紧为 `0700`，数据库文件初始化后收紧为 `0600`，并拒绝数据库文件符号链接。 | TC-19 实测新建多级目录为 `0700`，新建和已有数据库均为 `0600`。 |
| P0-10 | 外部交付待完成 | 真实 API 脚本已补齐直接回答、calculator 和工具型追问，但执行需要本机提供密钥；代码链接与录屏属于仓库外提交材料。 | 无 Key 时必须安全跳过，不能用固定模型 20/20 代替真实 API 证明。 |

代码级 P0-01 至 P0-09 已闭环，确定性验收为 **20/20**。因此当前可以判定 MVP 核心功能和代码内安全基线已经完成；`TASK.md` 的最终提交仍需补齐 P0-10 的真实 API 执行证据、代码链接和操作录屏。

## 1. 整改前结论（历史快照）

当前代码已经具备 `TASK.md` 要求的全部**功能类别**：自建 Agent loop、原生工具决策、3 个工具、session 持久化、追问、context 压缩、最大轮次、异常分类、trace 和确定性测试。

但当前只能判定为：

- **Happy path 核心功能已实现；**
- **安全与故障恢复尚未达到可交付状态；**
- **`TASK.md` 的完整提交要求尚未完成。**

在修复本报告的 P0 问题前，不建议宣称“核心功能已经完整完成”。最主要的原因不是缺少新功能，而是已有功能在中断恢复、权限隔离、上下文优先级、资源预算和秘密保护上仍有可复现缺口。

本次审查用临时数据库做了四个诊断探针，未修改生产代码：

1. 模拟在 assistant tool call 已保存、tool result 未保存时崩溃；重启后连续两个新 run 都以 `model_protocol_error` 失败，session 无法自行恢复。
2. 注入 `finish_reason="length"` 和部分文本；Runtime 将截断回答判定为 `succeeded`。
3. 将 `DEEPSEEK_API_KEY=leaked-secret` 放在普通 `content` 字段；当前 Redactor 原样保留。
4. 新建 SQLite 数据库的实际文件模式为 `0644`。

## 2. 整改前问题优先级

### P0：今天必须修

| ID | 类别 | 问题与证据 | 影响 | 最小必要修改 |
|---|---|---|---|---|
| P0-01 | 异常恢复 | 没有恢复遗留 `running` run。`AgentRuntime.run()` 直接追加新 run；`ContextBuilder._assert_tool_pairs()` 会拒绝崩溃留下的孤立 tool call。诊断中重启后的每次请求都永久失败。 | 一次进程退出、`Ctrl-C`、断电或强杀即可使 session 持续不可用，不满足“随时接着聊”。 | 在启动或新 run 前恢复同 session 的遗留 `running` run：标记为 `failed/interrupted`；最小安全策略是将其 `context_valid=0`，避免污染后续 context。增加 user-only、tool-call-before-result、tool-result-after-side-effect 三个崩溃点测试。 |
| P0-02 | 权限边界 | `ToolContext` 暴露原始 `sqlite3.Connection`。任何已注册工具都能绕过 repository，读取或修改所有 session、run、trace 和 reasoning 数据。`RunRepository.finish/get` 也只按 `run_id` 操作，没有显式 `session_id`。 | 违反系统骨架规定的“工具最小权限”和“所有 session 数据操作显式携带 session_id”；新增工具时可跨 session 访问。 | 从 `ToolContext` 移除原始连接，改为仅暴露绑定当前 session 的窄接口，例如 `SessionTodoStore.add/list`。Runtime 可以持有事务，但不要把连接交给 Tool。`RunRepository.get/finish` 增加 `session_id` 并在 SQL `WHERE` 中同时约束。 |
| P0-03 | 指令权限 | 压缩后的用户和工具文本被拼入 system prompt：`ContextBuilder._system_prompt()` 把 `session.summary` 放进 `<session_summary>`。摘要是历史原文的抽取，可能含“忽略之前规则”等用户输入。 | 把低优先级用户文本升级成 system 级指令，形成持久化 prompt injection；压缩后风险反而升高。 | system prompt 只保留固定系统规则；摘要作为明确标注的 `user`/memory 消息放入 messages，内容按“不可信历史数据”处理。增加摘要中含越权指令但系统规则仍有效的测试。 |
| P0-04 | 资源与副作用预算 | 只有模型步骤上限，没有用户输入长度、单响应工具数、run 总工具数、工具参数字节数、HTTP 响应大小和模型输出 token 的硬上限。一个模型响应可以携带任意多个工具调用，全部被顺序执行。 | 可造成内存/数据库膨胀、意外大量 todo 写入、长时间阻塞和不可控 API 成本；`max_steps` 无法限制单步爆炸。 | 增加小而明确的硬预算：用户输入上限；每响应和每 run 工具调用上限；tool arguments 上限；请求前 hard context limit；HTTP 有界读取；API 显式 `max_tokens`。超限使用独立错误码并停止，不能继续执行工具。 |
| P0-05 | 最大轮次语义 | 当第 `max_steps` 个模型响应仍含 tool calls 时，Runtime 会先执行所有工具，再返回 `max_steps`。当前 TC-13 正是在确认这种行为。 | 产生了副作用却没有机会让模型给最终回答；用户看到“任务未完成”后重试，未来新增非幂等工具时可能重复副作用。也不符合“达到上限后不再执行工具”的验收口径。 | 最后一个可用模型步骤若仍返回工具调用，不执行工具，直接以 `max_steps` 结束；或把“模型调用预算”和“工具预算”分开，并确保执行工具后至少保留一次最终回答机会。前者是最小修复。 |
| P0-06 | API Key 出站边界 | `DEEPSEEK_BASE_URL` 未校验，任意 `http://` 或攻击者域名都会收到 `Authorization: Bearer <key>`。 | 本地环境变量、错误配置或被污染的启动脚本可直接窃取 API Key。 | 默认只允许 `https://api.deepseek.com`（以及明确列出的官方路径）。如必须支持代理，使用显式高风险开关并至少强制 HTTPS；空 URL、用户名密码 URL、非 HTTPS 必须拒绝。 |
| P0-07 | Trace 隐私 | Trace 保存完整工具 `arguments` 与 `result`。Redactor 只按字段名递归；普通 `content/query/expression` 内的密钥、个人信息或访问令牌不会被识别。诊断已确认自由文本秘密原样保留。 | Trace 会复制用户敏感数据，README 中“脱敏 trace”的承诺并不成立。 | 默认只记录工具名、call ID、参数键名、成功状态、错误类型、耗时和结果大小；不要记录完整参数/结果。若确需内容，使用显式 allowlist，而不是依赖通用字符串猜测。增加自由文本秘密不落 trace 的测试。 |
| P0-08 | 模型终止状态 | `finish_reason` 被解析但没有参与成功判定；`length` 返回的部分文本会被当成最终成功答案。诊断已复现。 | 用户会把截断、资源不足或异常停止的回答误认为完整答案。 | 只把明确的 `stop`（无工具）和 `tool_calls`（有工具）视为正常；`length`、资源不足和未知 reason 使用明确错误码终止或受限恢复。 |
| P0-09 | 本地数据权限 | SQLite 文件由默认 umask 创建，审查环境实测为 `0644`；数据库包含完整对话、todo、trace 和工具轮 reasoning。 | 同机其他账号在目录允许时可能读取私有状态；“依赖本地文件权限”的安全边界没有真正落地。 | 对应用创建的目录使用 `0700`、数据库文件使用 `0600`；已有文件启动时检查并给出警告或收紧权限。不要修改用户指定目录中其他文件。 |
| P0-10 | 交付证明 | `acceptance/real_api_smoke.py` 存在，但当前环境没有 `DEEPSEEK_API_KEY`，真实 API 路径从未执行。代码链接和终端/网页录屏也不存在。 | 不满足 `TASK.md` 的“需要使用真实 LLM API、代码链接、操作录屏”。固定模型 17/17 不能替代真实协议验收。 | 配置真实密钥后执行并保存直接回答、calculator、工具追问的真实冒烟结果；随后生成代码仓库链接和录屏。密钥不得进入记录。 |

### P1：应在正式演示前修复

| ID | 类别 | 问题 | 失败表现 | 最小必要修改 |
|---|---|---|---|---|
| P1-01 | Context | 压缩阈值是软阈值。若当前输入本身过大、可压缩 run 不足，或保留的最近 run 已超过阈值，Compactor 返回不压缩，Runtime 仍继续请求模型。压缩后也没有检查是否仍超限。 | API 返回 400、成本异常，或长时间失败；用户只看到模型请求错误。 | 压缩后做一次 hard-limit 校验；仍超限就用 `context_overflow` 结束，不发送请求。 |
| P1-02 | 多工具原子性 | 同一模型响应中的多个工具每个单独提交事务。前一个 todo 成功、后一个存储失败时，前一个副作用保留，但整个 run 被标记失败且 context 隐藏。 | 用户认为任务完全失败，实际发生部分副作用。 | 同一 assistant 响应的工具批次使用一个事务；若做不到，RunResult/trace 必须明确报告已完成的部分副作用。 |
| P1-03 | 存储恢复 | 单条消息 JSON 损坏、Schema 版本异常、DB locked、磁盘满、初始化中断和 trace 写失败未覆盖；`_finish_failure_best_effort()` 静默吞掉最终存储错误。 | run 可能永久停在 `running`；session 每次继续都失败，且缺少可定位信息。 | 增加存储故障注入；启动时扫描并恢复 running run；对损坏 session 提供隔离/诊断错误，不继续追加失败消息。 |
| P1-04 | DB 一致性 | 数据库外键分别约束 `session_id` 和 `run_id`，但不能保证 message/trace 的 run 属于同一个 session。Repository API 也允许传入不匹配组合。 | 内部调用错误可产生跨 session 关联，查询时难以发现。 | Repository 写入时验证 `(run_id, session_id)`；下一 Schema 版本可增加组合唯一键和组合外键。 |
| P1-05 | 配置校验 | 数值配置只有正负校验，没有上限或 `isfinite`；`nan`/`inf`、极大 max steps/retries/timeout 可通过。thinking 布尔值的未知文本会被默认为 true；model 可为空。 | 无限等待、极高费用、运行时类型错误或难以理解的配置行为。 | 对每项配置设置合理上下界；浮点要求 finite；布尔值只接受明确集合；model 非空且限制长度。 |
| P1-06 | CLI 输入/输出 | user input、session title、session ID 没有长度与控制字符限制；模型答案直接输出到终端。 | 数据库膨胀、终端 ANSI/OSC 控制序列注入、列表排版破坏。 | 限制 user/title/session ID 长度和格式；Presenter 移除除换行、制表外的危险控制字符。 |
| P1-07 | Tool 参数解析 | `json.loads()` 只捕获 `JSONDecodeError`；深层 JSON 的 `RecursionError`、异常大整数和非标准 `NaN` 未统一转成 tool failure。 | Run 变成 `internal_error`，并把当前工具链设为无效，而不是让模型修正参数。 | 有界读取 arguments；禁用非标准常量；捕获解析资源错误并返回 `invalid_json`。 |
| P1-08 | API 重试可观察性 | HTTP 429/5xx/网络重试逻辑没有确定性测试；trace 只记录一次逻辑 model request，看不到实际 HTTP 尝试次数。 | README 声称的重试行为无法证明，费用和延迟也无法复盘。 | 注入 HTTP transport，确定性测试 400/401/402/422/429/500/503/timeout；trace 记录 attempt 次数和最终 HTTP 类别，不记录响应正文。 |
| P1-09 | 测试真实性 | TC-04/15 的“重启”只是重建 Application，并非真正退出子进程；TC-14 只检查摘要含事实，没有在压缩后实际追问并验证回答；TC-08 是跨模型步骤调用两个工具，不是同一响应的多个 tool calls。 | 关键验收名称与实际证明强度不一致。 | 增加 subprocess 重启用例；压缩后问早期事实；构造单个响应包含 2 个 tool calls 并验证串行顺序。 |
| P1-10 | 隔离覆盖 | TC-05 只验证消息和 todo，没有验证 summary、reasoning、run、trace 的跨 session 隔离。 | 核心查询当前看似隔离，但完整验收要求没有证据。 | 在 A/B session 分别触发压缩、工具 reasoning 和 trace，再逐类断言不可跨 session 读取。 |

### P2：可以作为已知限制留下

以下项目符合本地单用户 MVP 的范围，可以暂不实现，但必须在 README 中保持明确：

- 不提供用户认证；session ID 不是访问令牌，依赖本机账号和文件权限。
- 不承诺两个进程并发写同一个 session；暂不引入 WAL、锁租约或分布式协调。
- 工具 JSON Schema 校验器只支持项目声明的子集，不支持完整 JSON Schema Draft。
- `reasoning_content` 为协议连续性明文保存在本地；在文件权限修复后，静态加密可继续作为已知限制。
- Context 使用字符/token 粗估和确定性抽取摘要，不保证复杂语义信息全部保留。
- Search 是固定 Mock，不是实时联网结果。
- Todo 只有新增和查看；模型自主新增 todo 不含人工审批，只适用于低风险副作用。
- 无 trace 自动清理、数据保留周期、流式输出、取消协议和性能 SLA。
- `MVA_DB_PATH` 可由本机操作者指定任意路径；在单用户可信运维假设下保留，但不得将不可信远程输入映射到该变量。

## 3. 整改前未覆盖的异常路径

当前 17 个场景覆盖了主要 happy path 和一部分故障，但下列路径没有被有效证明：

### 模型/API

- 400、402、422、429、500、502、503、504 的真实分类和重试次数；
- DNS、TLS、连接超时、读取超时、连接中断；
- 响应体过大、非 UTF-8、合法 JSON 但字段类型错误；
- `finish_reason=length`、未知 finish reason、资源不足；
- 同一响应重复 call ID、超多 tool calls、超大 arguments；
- API 重试后成功，以及重试耗尽后的 trace。

### Tool

- arguments 不是合法 JSON、不是 object、缺 required、包含额外字段、超过长度/范围；
- `NaN`、超深 JSON、异常大整数；
- calculator 的代码注入表达式、极端幂、极长 AST；
- search 只有空白字符；
- todo 重复 add 的 `created=false`；
- 同一个模型响应包含多个工具调用；
- 第 `max_steps` 步返回副作用工具调用。

### Storage/Session

- 进程在 user message、assistant tool call、tool result、run finish 四个时点中断；
- stale `running` run 的启动恢复；
- DB locked、只读目录、磁盘满、损坏文件、Schema 版本错误；
- message/tool_calls JSON 损坏；
- summary 更新冲突和 compaction 写失败；
- trace 写失败、run 终态写失败；
- summary、reasoning、run、trace 的双 session 隔离；
- 真正跨进程退出与恢复。

### Context/隐私

- 压缩后实际回答早期事实；
- 压缩后仍超过 hard context limit；
- 摘要中的 prompt injection；
- 自由文本秘密位于 query/content/expression 时不落 trace；
- 数据库权限检查；
- 模型输出的终端控制字符。

## 4. 整改前缺少的输入校验

按输入来源整理如下：

| 来源 | 当前已有 | 仍缺少 |
|---|---|---|
| 用户输入 | 非空 | 最大长度、控制字符策略、hard token budget |
| Session | 随机创建 ID、SQL 参数化 | 外部 session ID 格式/长度、title 长度/控制字符 |
| 环境配置 | 部分正数校验 | Base URL HTTPS/host、model 非空、数值上限、finite float、严格布尔值 |
| 模型响应 | 基本字段解析、call ID 唯一 | finish reason 语义、响应字节上限、工具调用数、参数字节数、content/reasoning 长度 |
| Tool JSON | 基础 Schema 子集 | 深度/大小、非标准常量、解析资源异常、operation 相关条件 |
| 持久化状态 | tool call/result 配对 | 损坏 JSON、跨 session run 关联、stale running run |
| CLI 输出 | JSON trace 格式化 | ANSI/OSC 等终端控制字符过滤 |

## 5. 整改前失败体验最差的场景

按用户影响排序：

1. **工具链中途退出后 session 永久失败。** 用户每次重试都会新增一个失败 run，但原始孤立 call 一直存在。
2. **截断回答被标记成功。** 用户无法知道答案不完整。
3. **最后一步执行 todo 后返回 max steps。** 用户看到失败，但副作用已经发生。
4. **Context 仍超限却继续请求。** 用户等待 API 重试后才得到泛化错误。
5. **多个工具部分提交。** 用户认为整体失败，数据库却已有部分变化。
6. **存储终态写失败被静默吞掉。** 用户得到错误，但 trace/run 可能仍是 `running`。
7. **自由文本秘密进入 trace。** CLI 的 `traces` 命令会直接打印。
8. **模型或 session 文本含终端控制序列。** 终端展示可能被操控。

## 6. 整改前对照 TASK.md 的完成状态

### 已完成

| TASK 要求 | 状态 | 证据 |
|---|---|---|
| 核心 Runtime 自行实现 | 已实现 | `src/mva/runtime/agent.py`，无 Agent 框架依赖 |
| 接收输入、直接回答/工具、继续 loop | 已实现 | `AgentRuntime.run()` |
| 至少三个工具 | 已实现 | calculator、Mock search、todo |
| 工具注册、描述、Schema | 已实现 | `ToolRegistry` / `ToolSpec` |
| 解析思考、工具调用、最终答案 | 已实现 | `DeepSeekClient._parse_response()`；私有 reasoning 不对外展示 |
| Session 隔离与持久化 | 名义实现 | SQLite 分层和 session_id 查询已存在；但权限 API 和中断恢复仍有 P0 |
| 最大轮次 | 已实现但语义需修 | 有 max steps；最后一步仍会执行工具 |
| 普通追问、工具追问 | 已实现 | TC-06、TC-07 |
| Context 压缩 | 已实现但安全边界需修 | 有滚动摘要；当前错误地提升进 system prompt |
| 基本异常处理 | 部分完成 | 已分类主要错误；缺中断、存储、超限、finish reason |
| 工具 trace/日志 | 已实现但脱敏不足 | Trace 完整；自由文本秘密可泄漏 |
| 测试用例 | 已实现 | 当前 TC-01 至 TC-17 通过，但覆盖缺口见本报告 |
| README | 已完成 | 含运行、设计、memory 召回与放置 |
| AI Prompt 与问题解决记录 | 已完成 | `docs/AI_PROMPTS.md`、`docs/PROBLEM_SOLVING.md` |

### 未完成

| TASK 提交项 | 状态 | 说明 |
|---|---|---|
| 真实 LLM API 运行证明 | 未完成 | 脚本存在，但当前因无 Key 只执行了安全跳过 |
| 代码链接 | 未完成 | 当前只有本地工作区 |
| 终端或网页操作录屏 | 未完成 | 尚未生成 |
| 可恢复 session 的故障级保证 | 未完成 | 正常重启可恢复；工具链中途退出会污染 session |
| 安全可交付 | 未完成 | 本报告 P0-01 至 P0-09 仍需处理 |

因此，准确说法应是：

> MVP 的功能骨架和正常业务闭环已经开发完成；
> 核心功能尚未达到故障安全和最终交付完成状态。

## 7. 原最小必要修改顺序

不扩功能的前提下，建议严格按以下顺序处理：

1. **先修 session 可恢复性：** stale run 恢复、异常 run 隔离、3 个崩溃点测试。
2. **收紧内部权限：** ToolContext 去连接、session-scoped capability、RunRepository 带 session_id。
3. **加硬预算与终止语义：** 输入/context/tool/response 上限、finish reason、最后一步不执行工具。
4. **堵秘密泄漏：** Base URL allowlist/HTTPS、trace 改记元数据、DB `0600`。
5. **修摘要优先级：** summary 从 system 移到不可信 memory 消息。
6. **补关键验收：** 同响应多工具、压缩后真实追问、跨进程重启、HTTP 重试、完整 session 隔离。
7. **最后做真实 API 与交付材料：** 真实冒烟、代码链接、录屏。

完成 1–5 后再运行现有 TC-01 至 TC-17，并新增上述最小回归用例。P2 项保持在 README 的“当前边界”中即可，不应在这一轮继续扩展。
