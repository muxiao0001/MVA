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

处理：Runtime 为每个工具调用开启 SQLite 事务，把 `ToolContext` 限定在该连接上；todo 写入、tool result 消息和工具 trace 同时提交或同时回滚。

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

## 9. 验证结果

- `python -m compileall -q src acceptance`：通过；
- `python acceptance/run_all.py`：TC-01 至 TC-17 全部通过；
- CLI session 创建、列表和恢复入口：通过；
- 真实 API 冒烟：脚本已提供；只有存在 `DEEPSEEK_API_KEY` 时执行，否则安全跳过。

