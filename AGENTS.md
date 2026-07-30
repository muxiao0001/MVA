# 仓库指南

## 项目结构与模块组织

本仓库目前处于设计阶段。开发前先阅读：`TASK.md`（原始任务）、`REQUIREMENTS_ANALYSIS.md`（需求与验收标准）、`SOLUTION_OPTIONS.md`（方案权衡）和 `SYSTEM_SKELETON.md`（模块边界）。

实现应遵循规划中的 `src/mva/` 结构：Agent 循环放在 `runtime/`，模型适配放在 `model/`，工具定义与注册放在 `tools/`，持久化逻辑放在 `storage/`，session、context 和 trace 分别放入对应包。Prompt 存放于 `prompts/`，验收场景和固定数据分别存放于 `acceptance/scenarios/` 与 `acceptance/fixtures/`，补充设计文档放入 `docs/`。禁止提交 `var/` 中的本地运行数据和 `.env`。

## 构建、测试与开发命令

项目统一使用 Conda 的 `MVA` 环境。可执行代码尚未提交；新增项目骨架后应保留以下标准入口，并同步更新 `README.md`：

```bash
conda activate MVA
python -m pip install -e .
python -m mva
python acceptance/run_all.py
```

`pip install -e .` 以可编辑模式安装项目；`python -m mva` 启动 CLI；验收脚本运行可重复场景。依赖变更应记录在 `pyproject.toml`。真实 API 冒烟测试须与确定性测试分开。

## 编码风格与命名规范

Python 代码使用四空格缩进，公共接口必须添加类型注解，模块保持单一职责。函数、变量和模块使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。工具名使用小写标识符，如 `calculator`、`mock_search`。模型供应商相关对象只能存在于 `model/`；CLI 和工具不得直接调用 LLM。

## 测试指南

测试应覆盖直接回答、合法与非法工具调用、最大轮次终止、session 隔离与重启恢复、context 压缩、存储异常和 trace 脱敏。场景文件命名为 `tc_<编号>_<行为>.py`。使用临时 SQLite 数据库和固定模型响应保证结果稳定。缺少 API 凭据时，真实 DeepSeek 测试必须安全跳过。

## Commit 与 Pull Request 规范

每个 commit 只包含一个明确目的，并使用 Conventional Commits，例如 `feat(runtime): enforce max steps`、`fix(storage): isolate session queries` 或 `docs: clarify recovery flow`。提交前检查暂存范围，禁止混入本地数据和密钥。

PR 必须说明变更内容、对应需求、验证方式以及安全或持久化影响。关联相关 issue；CLI 行为发生变化时，附上终端输出、截图或录屏。

## 安全与 Agent 约束

API Key 只能从环境变量读取，不得写入源码、数据库、日志或文档。不得记录原始 `reasoning_content`。核心 Agent Runtime 禁止依赖现有 Agent 框架。所有 session 范围内的数据查询和变更都必须显式携带 `session_id`。
