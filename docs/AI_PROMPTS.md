# AI Prompt 记录

本文件记录实现阶段使用 AI 辅助开发时的任务约束与关键提示。未记录、也不得记录真实 API Key 或模型私有推理。

## 初始任务提示

```text
从零实现一个最小可用 Agent。核心 Runtime 不依赖现有 Agent 框架。
实现：有限 Agent loop、原生工具选择与调用、至少三个统一注册工具、
可恢复且隔离的 session、context 管理与基础压缩、异常处理、脱敏 trace、
确定性测试用例，以及真实 LLM API 入口。
```

## 设计收敛提示

```text
以 TASK.md、PROBLEM_DEFINITION.md、REQUIREMENTS_ANALYSIS.md、
SOLUTION_OPTIONS.md 和 SYSTEM_SKELETON.md 为唯一产品边界。
采用方案 A：DeepSeek 原生 Tool Calls + 自建有限循环 + SQLite 分层状态。
不得引入 Web、多 Agent、RAG、事件溯源或生产级并发。
```

## Context 与安全提示

```text
完整历史与模型可见 context 分离；只压缩已经闭合的 run，
不得拆分 assistant tool_call 和 tool result。
todo 是独立业务状态，不依赖摘要保存。
reasoning_content 只在 DeepSeek 工具协议需要时续传，
禁止进入 CLI、普通 trace、README 和录屏。
```

## 验收生成提示

```text
不使用测试框架。通过可替换 ModelClient 的固定响应源构造 TC-01 至 TC-20；
每个场景使用临时 SQLite 数据库，输出预期、实际和 PASS/FAIL。
真实 DeepSeek 冒烟单独执行，缺少凭据时安全跳过。
```

## P0 安全整改提示

```text
停止新增功能，按照 SECURITY_QUALITY_AUDIT.md 的 P0 顺序做最小整改：
恢复并隔离 stale running run；移除 ToolContext 的数据库连接；
摘要不得提升为 system 指令；给输入、context、工具和模型响应设置硬预算；
最后一步不得执行工具副作用；限制 API Key 的 Base URL 出站目标；
trace 不保存原始工具参数/结果；拒绝截断答案；收紧 SQLite 文件权限。
新增回归必须继续使用固定模型和临时数据库，真实 API 证明保持独立。
```

## 人工检查点

- 工具列表必须由 Registry 生成，而不是在 Runtime 为三个工具硬编码分支；
- 所有 session 级 repository 操作必须显式带 `session_id`；
- todo 副作用与 tool result 必须处于同一事务；
- run 终态只能从 `running` 写入一次；
- trace 只能记录可公开决策和脱敏数据；
- 真实 API 与固定模型验收不得混在一起。
