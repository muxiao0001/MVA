# 问题解决记录

## 1. DeepSeek thinking 与工具调用续传

问题：thinking 模式的普通回答与工具回答对 `reasoning_content` 的续传要求不同。工具轮若漏传会导致后续请求返回 400，但全部公开或写日志又会泄露私有推理。

处理：

- `ModelResponse` 单独解析 `content`、`reasoning_content` 和 `tool_calls`；
- 只有包含工具调用的 assistant 消息才保留原始推理；
- `ContextBuilder` 只在重放该工具 assistant 消息时加入 `reasoning_content`；
- CLI、决策摘要、压缩文本和 trace 均不读取此字段。

## 2. Context 压缩不能破坏工具协议

问题：简单按消息条数截断，可能留下孤立 tool result 或缺失其 assistant tool call。

处理：

- 每条消息绑定 `run_id`，每个用户输入对应一个 run；
- 压缩候选仅来自已结束、`context_valid=1` 的 run；
- 以完整 run 的最后 seq 为压缩边界，并保留最近若干完整 run；
- 构建 context 时再次校验 call ID 配对，发现异常直接分类失败；
- 原消息不删除，session 只更新摘要和压缩游标。

## 3. Todo 副作用与工具结果一致性

问题：若先提交 todo，再保存 tool result，第二步失败会导致模型认为工具失败，但待办实际已新增。

处理：Runtime 为每个工具调用开启 SQLite 事务，但不把 connection 交给工具。`todo` 只获得绑定当前 session 与当前事务的 `SessionTodoStore.add/list`；todo 写入、tool result 消息和工具 trace 同时提交或同时回滚。

## 4. 防止副作用重复

问题：模型修正参数或内部重试可能重复新增待办。

处理：

- `(session_id, normalized_content, status)` 唯一；
- `(session_id, source_tool_call_id)` 唯一；
- 内容已存在时返回 `created=false`，明确告诉模型没有创建副本。

## 5. 不依赖第三方 JSON Schema 包

问题：目标 Conda 环境没有 `jsonschema`，且项目应尽量小。

处理：Registry 实现本项目工具实际使用的 JSON Schema 子集：object、required、properties、additionalProperties、string、integer、number、array、enum 和范围约束。Schema 仍以标准工具格式发送给模型；不声称实现完整 JSON Schema Draft。

## 6. Calculator 安全

问题：直接 `eval` 会把计算工具变成任意代码执行入口。

处理：仅解析 `ast.Expression`，白名单允许数字常量、指定二元/一元运算符；限制表达式长度、数值大小和指数绝对值，拒绝名称、属性、调用、下标与容器。

## 7. API 错误与有限恢复

问题：对鉴权或参数错误重试无意义，对服务类错误完全不重试又降低演示稳定性。

处理：

- 401、402、普通 4xx 立即分类失败；
- 429、500、502、503、504 和网络错误最多重试 2 次；
- 使用 1.2 秒为基准的指数退避；
- Runtime 仍受 8 次逻辑模型步骤上限约束。

## 8. 当前 MVA 环境的安装策略

问题：本机 `MVA` Conda 环境被标记为 PEP 668 外部管理，`pip install -e .` 被环境策略拒绝。

处理：项目仍保留标准 `pyproject.toml` 和可编辑安装入口；本机验证使用 `PYTHONPATH=src`，不强行突破环境管理策略，也不引入第三方依赖。

## 9. P0 安全审查整改

问题：正常业务闭环完成后，安全审查仍复现了中断 run 污染 session、工具获得原始数据库连接、摘要提升到 system、缺少资源预算、最后一步继续执行副作用、API Key 可发往任意 Base URL、trace 复制自由文本秘密、截断答案误判成功和数据库文件为 `0644`。

处理：

- 每个新 run 前，将同 session 遗留的 `running` run 标记为 `failed/interrupted` 并设置 `context_valid=0`；
- `ToolContext` 只暴露最小能力，`RunRepository.get/finish`、message 和 trace 写入同时校验 `session_id` 与 `run_id`；
- 固定 system prompt 与非可信历史摘要分离，摘要作为标注后的 `user` memory 消息；
- 增加用户输入、hard context、单响应/单 run 工具数、工具参数、模型输出 token/字符和 HTTP 响应字节预算；
- 最后一个模型步骤若仍要求工具，不保存该工具请求、不执行副作用，直接以 `max_steps` 结束；
- Base URL 默认限制为 DeepSeek 官方 HTTPS 地址；显式允许代理时仍拒绝 HTTP、URL 凭据、query 与 fragment；
- 工具 trace 只记录名称、call ID 短哈希、长度和状态，不复制参数与结果正文；
- 只有 `stop` 和 `tool_calls` 是正常结束原因，`length` 使用 `model_output_truncated` 失败；
- 应用创建的数据库目录使用 `0700`、数据库文件使用 `0600`，并拒绝数据库文件符号链接。

## 10. 验证结果

- `python -m compileall -q src acceptance`：通过；
- `python acceptance/run_all.py`：TC-01 至 TC-20 全部通过；
- TC-04 使用两个独立 Python 进程验证退出后恢复；TC-14 实际执行压缩后的早期事实追问；
- CLI session 创建、列表和恢复入口：通过；
- HTTP Adapter 的 503 有限重试与 401 不重试通过确定性故障注入；
- 工具参数的 Schema、非标准 JSON 常量与 64 层嵌套上限均通过；
- 真实 API 冒烟：`deepseek-v4-flash` 的直接回答、calculator、工具型追问和 `search → todo` 全部通过；
- `.env` mode 为 `0600`、被 Git 忽略，当前 API Key 未出现在任何 Git 跟踪文件中；
- 真实 API 脱敏证据见 `docs/REAL_API_TEST_EVIDENCE.md`。
