# Minimum Viable Agent

一个不依赖现有 Agent 框架的本地 CLI Agent。项目自行实现有限循环、原生 Tool Calls 调度、session/context、SQLite 持久化、基础压缩、异常分类和脱敏 trace；模型适配器调用真实 DeepSeek OpenAI 兼容 API。


## 已实现能力

- 自建 Agent loop：直接回答、单工具、多工具连续调用，最多 8 次模型调用；最后一个步骤不会再执行工具副作用；
- 统一工具注册：`calculator`、固定 Mock `search`、session 级 `todo`；
- DeepSeek thinking + tool call 协议：工具轮的 `reasoning_content` 只在内部保存和续传；
- 多 session 创建、列表、恢复、隔离；新 run 会隔离上次异常退出留下的未完成 run；
- SQLite 分层保存完整消息、滚动摘要、todo、run 与 trace；应用创建的数据库文件收紧为 `0600`；
- 约 4 字符/token 的上下文估算，超过阈值后只压缩已闭合 run，超过 hard limit 时拒绝发送；
- API、模型协议、工具、存储、资源预算与轮次上限的明确终止；
- 20 个不依赖测试框架的确定性验收场景，以及独立真实 API 冒烟脚本。

核心 Runtime 没有使用 LangGraph、OpenHands、OpenClaw、Agents SDK、AutoGen 或 Pydantic AI。项目也没有运行时第三方依赖；HTTP、SQLite、AST 和 CLI 均使用 Python 标准库。

## 环境与安装

要求 Python 3.11+，没有使用外部依赖。仓库本地使用 Conda 的 `MVA` 环境：

```bash
conda activate MVA
python -m pip install -e .
```

如果本机的 `MVA` 环境启用了 PEP 668、拒绝向环境安装包，可不修改环境，直接使用：

```bash
export PYTHONPATH=src
```

复制配置示例、收紧权限并在当前 shell 中加载。项目不会自动读取 `.env`，避免无意加载错误文件：

```bash
cp .env.example .env
chmod 600 .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
set -a
source .env
set +a
```

`.env` 只应包含受信任的 shell 变量赋值。不要提交 `.env`、数据库或真实 API Key。

默认只允许 `https://api.deepseek.com` 接收 API Key。确需使用兼容代理时，必须同时设置 `MVA_ALLOW_CUSTOM_BASE_URL=true`；自定义地址仍强制 HTTPS，且不得包含 URL 凭据、query 或 fragment。

## CLI

```bash
# 无参数：创建新 session 并进入聊天
python -m mva

# 创建、列出、恢复
python -m mva new --title demo
python -m mva new --title demo --no-chat
python -m mva sessions
python -m mva chat s_xxxxxxxxxxxx

# 查看一个 session 或 run 的脱敏 trace
python -m mva traces s_xxxxxxxxxxxx
python -m mva traces s_xxxxxxxxxxxx --run run_xxxxxxxxxxxxxxxx
```

聊天中使用 `/exit` 退出。重新启动后，用 `sessions` 找到 ID，再用 `chat` 恢复。

## 系统设计

主链路是：

```text
CLI
  → AgentRuntime（有限循环/终止）
    → ContextBuilder / ContextCompactor
    → DeepSeekClient（仅 API 协议）
    → ToolRegistry（白名单 + JSON Schema 校验）
      → calculator / mock search / todo
    → SQLite repositories
    → TraceRecorder（脱敏）
```

每次用户输入对应一个 `run_id`。Runtime 先原子保存 run 与用户消息，然后在 `max_steps` 内重复：

1. 从指定 `session_id` 组装 context；
2. 调用模型并解析 `content`、`tool_calls`、`reasoning_content`、`finish_reason`；
3. 没有工具调用且有有效内容时结束；
4. 有工具调用时，按顺序校验和执行，将每个结果用相同 call ID 回传，再继续模型循环；
5. 非法输出、截断回答、资源超限、服务错误、存储错误或达到上限时进入明确终态。

同一模型响应的多个工具调用在 P0 中串行执行。todo 副作用和对应 tool result 在同一个 SQLite 事务内提交，避免“待办已新增但模型收到失败”。重复的开放待办会返回 `created=false`，不会静默创建副本。

如果进程在 run 中途退出，下次向同一 session 发起请求前，遗留的 `running` run 会被标记为 `failed/interrupted` 且从后续 context 隔离。该策略保证 session 可继续使用，但不会自动重放可能已发生的工具副作用。

## Session、context 与 memory

四类状态明确分离：

| 状态 | 保存位置 | 召回时机 | 放入模型 context |
|---|---|---|---|
| 完整对话与工具协议消息 | `messages` | 每次模型调用前 | 只放摘要游标之后的消息 |
| 滚动会话摘要 | `sessions.summary` | 每次模型调用前 | 作为明确标注的非可信 `user` memory 消息；不会进入 system prompt |
| todo 业务状态 | `todos` | 模型调用 `todo list` 时 | 不自动塞历史，以工具查询结果为准 |
| run/trace | `runs`、`trace_events` | 调试与验收时 | 不放入模型 context |

所有业务查询和变更都显式携带 `session_id`。不存在跨 session 的用户级长期记忆。

### 压缩策略

默认参数：

- `MVA_CONTEXT_TOKEN_THRESHOLD=12000`
- `MVA_HARD_CONTEXT_TOKEN_LIMIT=64000`
- `MVA_CONTEXT_RETAIN_RUNS=4`
- 估算规则：约 4 字符/token，加消息和工具 Schema 固定开销；
- 滚动摘要最大约 6,000 字符；
- 仅压缩已经结束且工具调用完全闭合的 run；
- 完整原始消息不删除，只推进 `compacted_through_seq`；
- 摘要更新失败会回滚事务，不改变原游标。

采用确定性抽取摘要而非额外 LLM 请求，保证验收稳定、压缩失败可控。可在录屏时调低阈值，例如：

```bash
export MVA_CONTEXT_TOKEN_THRESHOLD=300
export MVA_CONTEXT_RETAIN_RUNS=2
```

## 工具注册规范

工具实现 `Tool` 接口并提供：

- 唯一小写名称；
- 面向模型的描述；
- JSON 参数 Schema；
- `execute(arguments, ToolContext, tool_call_id)`；
- 统一 `ToolResult`。

`ToolRegistry` 在执行前拒绝未知工具、畸形 JSON、非 object 参数和不符合本项目 Schema 子集的参数。`calculator` 只解释白名单 AST 节点，不执行 `eval`；`search` 的每次输出均带 Mock 声明；`todo` 只能访问当前 session 的 repository。

`ToolContext` 不暴露 SQLite connection。普通工具只能得到 session/run 标识；`todo` 额外得到绑定当前 session 和当前事务的 `SessionTodoStore.add/list` 窄能力，不能查询其他 session。

## Trace 与异常

Trace 至少包含 run/session ID、步骤、事件类型、工具名、状态、耗时、错误类型和终止原因。工具事件只记录 call ID 的短哈希、参数/结果长度与成功状态，不保存原始参数或结果；模型的私有推理不会进入 CLI 或 trace。CLI 展示层会移除终端控制字符，避免模型答案或 session 标题触发 ANSI/OSC 控制行为。

API 错误被分类为配置、鉴权、余额、限流、请求、响应过大和服务错误。429/500/502/503/504 与网络失败最多自动重试 2 次，退避为 1.2s、2.4s；400/401/402/422 等不可恢复请求不会反复重试。`finish_reason=length` 不会被当作成功答案。

## 验收

确定性场景使用固定模型响应，不依赖网络或回答文案：

```bash
python acceptance/run_all.py
```

覆盖 TC-01 至 TC-20：原有核心业务场景，以及异常 run 恢复、最小工具权限、跨 session repository 边界、Base URL 出站限制、trace 内容最小化、数据库权限、输入/context/tool/HTTP/模型输出预算和截断终止。结果同时写到被 Git 忽略的 `acceptance/results/latest.json`。

真实 API 冒烟与确定性验收分开：

```bash
python acceptance/real_api_smoke.py
```

未设置 `DEEPSEEK_API_KEY` 时脚本安全跳过；设置后会用当前配置的模型验证直接回答、模型自主 calculator、带历史工具结果的工具型追问，以及 `search → todo` 真实多工具链。脚本使用临时 `0600` SQLite 数据库，不打印密钥，并将不含回答正文和秘密的结果写入 `acceptance/results/real_api_latest.json`。

2026-08-01 的真实执行记录见 [真实 API 验证记录](docs/REAL_API_TEST_EVIDENCE.md)。



## 配置项

| 环境变量 | 默认值 |
|---|---|
| `DEEPSEEK_API_KEY` | 无，必须外部提供 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` |
| `MVA_ALLOW_CUSTOM_BASE_URL` | `false` |
| `MVA_THINKING_ENABLED` | `true` |
| `MVA_DB_PATH` | `var/agent.db` |
| `MVA_MAX_STEPS` | `8` |
| `MVA_MAX_USER_INPUT_CHARS` | `20000` |
| `MVA_CONTEXT_TOKEN_THRESHOLD` | `12000` |
| `MVA_HARD_CONTEXT_TOKEN_LIMIT` | `64000` |
| `MVA_CONTEXT_RETAIN_RUNS` | `4` |
| `MVA_MAX_TOOL_CALLS_PER_RESPONSE` | `4` |
| `MVA_MAX_TOOL_CALLS_PER_RUN` | `8` |
| `MVA_MAX_TOOL_ARGUMENTS_CHARS` | `16000` |
| `MVA_MAX_MODEL_OUTPUT_TOKENS` | `4096` |
| `MVA_MAX_MODEL_OUTPUT_CHARS` | `200000` |
| `MVA_MAX_HTTP_RESPONSE_BYTES` | `2000000` |
| `MVA_API_MAX_RETRIES` | `2` |
| `MVA_API_RETRY_BASE_SECONDS` | `1.2` |
| `MVA_MODEL_TIMEOUT_SECONDS` | `90` |

## 当前边界

- 单 Agent、文本 CLI、本地部署；
- 不提供用户认证；session ID 不是访问令牌，安全边界是运行程序的本机账号；
- 不提供真实联网搜索、Web、多 Agent、RAG 或跨 session 记忆；
- todo 仅新增和查看；
- 不承诺两个进程同时写同一 session；
- `reasoning_content` 为满足工具协议而明文保存在本地 SQLite；数据库文件会收紧为 `0600`，但 P0 不做静态加密；
- 中断恢复会隔离未完成 run，不自动判断或补偿已经提交的外部副作用；
- 工具 JSON Schema 校验只实现本项目声明使用的子集；
- 无 trace 自动清理、数据保留周期、流式输出、取消协议或性能 SLA；
- `.env`、`var/` 与验收结果不提交。

## 交付内容

开发中的提示和问题记录见 [docs/AI_PROMPTS.md](docs/AI_PROMPTS.md) 与 [docs/PROBLEM_SOLVING.md](docs/PROBLEM_SOLVING.md)。
录屏网盘链接： https://pan.baidu.com/s/1owyuEHZTfe6CaJtZkFjvXw?pwd=q8dn 提取码: q8dn 
架构设计题见 [./Agent架构设计题.md](./Agent架构设计题.md)