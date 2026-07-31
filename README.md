# Minimum Viable Agent

一个不依赖现有 Agent 框架的本地 CLI Agent。项目自行实现有限循环、原生 Tool Calls 调度、session/context、SQLite 持久化、基础压缩、异常分类和脱敏 trace；模型适配器调用真实 DeepSeek OpenAI 兼容 API。

## 已实现能力

- 自建 Agent loop：直接回答、单工具、多工具连续调用，最多 8 次模型调用；
- 统一工具注册：`calculator`、固定 Mock `search`、session 级 `todo`；
- DeepSeek thinking + tool call 协议：工具轮的 `reasoning_content` 只在内部保存和续传；
- 多 session 创建、列表、恢复、隔离，退出进程后仍可继续；
- SQLite 分层保存完整消息、滚动摘要、todo、run 与 trace；
- 约 4 字符/token 的上下文估算，超过阈值后只压缩已闭合 run；
- API、模型协议、工具、存储与轮次上限的明确终止；
- 17 个不依赖测试框架的确定性验收场景，以及独立真实 API 冒烟脚本。

核心 Runtime 没有使用 LangGraph、OpenHands、OpenClaw、Agents SDK、AutoGen 或 Pydantic AI。项目也没有运行时第三方依赖；HTTP、SQLite、AST 和 CLI 均使用 Python 标准库。

## 环境与安装

要求 Python 3.11+。仓库约定使用 Conda 的 `MVA` 环境：

```bash
conda activate MVA
python -m pip install -e .
```

如果本机的 `MVA` 环境启用了 PEP 668、拒绝向环境安装包，可不修改环境，直接使用：

```bash
export PYTHONPATH=src
```

复制配置示例并在 shell 中导出真实密钥；项目不会自动读取 `.env`，避免无意加载错误文件：

```bash
export DEEPSEEK_API_KEY='your-key'
export DEEPSEEK_BASE_URL='https://api.deepseek.com'
export DEEPSEEK_MODEL='deepseek-v4-pro'
```

不要提交 `.env`、数据库或真实 API Key。

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
5. 非法输出、服务错误、存储错误或达到上限时进入明确终态。

同一模型响应的多个工具调用在 P0 中串行执行。todo 副作用和对应 tool result 在同一个 SQLite 事务内提交，避免“待办已新增但模型收到失败”。重复的开放待办会返回 `created=false`，不会静默创建副本。

## Session、context 与 memory

四类状态明确分离：

| 状态 | 保存位置 | 召回时机 | 放入模型 context |
|---|---|---|---|
| 完整对话与工具协议消息 | `messages` | 每次模型调用前 | 只放摘要游标之后的消息 |
| 滚动会话摘要 | `sessions.summary` | 每次模型调用前 | 合并到 system prompt 的 `<session_summary>` |
| todo 业务状态 | `todos` | 模型调用 `todo list` 时 | 不自动塞历史，以工具查询结果为准 |
| run/trace | `runs`、`trace_events` | 调试与验收时 | 不放入模型 context |

所有业务查询和变更都显式携带 `session_id`。不存在跨 session 的用户级长期记忆。

### 压缩策略

默认参数：

- `MVA_CONTEXT_TOKEN_THRESHOLD=12000`
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

## Trace 与异常

Trace 至少包含 run/session ID、步骤、事件类型、工具名、状态、耗时、错误类型和终止原因。API Key、authorization、password、secret、token 与 `reasoning_content` 字段会递归脱敏；模型的私有推理不会进入 CLI 或 trace。

API 错误被分类为配置、鉴权、余额、限流、请求和服务错误。429/500/502/503/504 与网络失败最多自动重试 2 次，退避为 1.2s、2.4s；400/401/402/422 等不可恢复请求不会反复重试。

## 验收

确定性场景使用固定模型响应，不依赖网络或回答文案：

```bash
python acceptance/run_all.py
```

覆盖 TC-01 至 TC-17：直接回答、三种工具、持久化与隔离、两类追问、多工具链、非法调用、API/工具异常、最大轮次、context 压缩、工具消息配对、推理隐私和 trace 完整性。结果同时写到被 Git 忽略的 `acceptance/results/latest.json`。

真实 API 冒烟与确定性验收分开：

```bash
python acceptance/real_api_smoke.py
```

未设置 `DEEPSEEK_API_KEY` 时脚本安全跳过；设置后会用 `deepseek-v4-pro` 验证一次直接回答和一次模型自主 calculator 工具链。

## 录屏建议

1. 运行真实 API 冒烟；
2. 创建 session，演示直接回答、calculator、search → todo；
3. 创建 A/B 两个 session，分别写入 todo 并展示隔离；
4. 退出后重新启动，恢复一个 session；
5. 调低压缩阈值，连续对话后追问早期事实；
6. 展示缺失密钥或非法计算，以及对应 `traces`；
7. 运行 `python acceptance/run_all.py` 展示 17/17。

## 配置项

| 环境变量 | 默认值 |
|---|---|
| `DEEPSEEK_API_KEY` | 无，必须外部提供 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` |
| `MVA_DB_PATH` | `var/agent.db` |
| `MVA_MAX_STEPS` | `8` |
| `MVA_CONTEXT_TOKEN_THRESHOLD` | `12000` |
| `MVA_CONTEXT_RETAIN_RUNS` | `4` |
| `MVA_API_MAX_RETRIES` | `2` |
| `MVA_API_RETRY_BASE_SECONDS` | `1.2` |
| `MVA_MODEL_TIMEOUT_SECONDS` | `90` |

## 当前边界

- 单 Agent、文本 CLI、本地部署；
- 不提供真实联网搜索、Web、多 Agent、RAG 或跨 session 记忆；
- todo 仅新增和查看；
- 不承诺两个进程同时写同一 session；
- `reasoning_content` 为满足工具协议而明文保存在本地 SQLite，安全边界是本机文件权限；P0 不做静态加密；
- `var/` 与验收结果不提交。

设计依据见 [SYSTEM_SKELETON.md](SYSTEM_SKELETON.md)，需求与验收口径见 [REQUIREMENTS_ANALYSIS.md](REQUIREMENTS_ANALYSIS.md)，开发中的提示和问题记录见 [docs/AI_PROMPTS.md](docs/AI_PROMPTS.md) 与 [docs/PROBLEM_SOLVING.md](docs/PROBLEM_SOLVING.md)。

