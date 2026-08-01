# 真实 DeepSeek API 验证记录

> 执行日期：2026-07-31  
> 模型：`deepseek-v4-flash`  
> Base URL 主机：`api.deepseek.com`

## 执行方式

```bash
chmod 600 .env
set -a
source .env
set +a
PYTHONPATH=src conda run -n MVA python acceptance/real_api_smoke.py
```

## 验证结果

| 场景 | 结果 | 关键证据 |
|---|---|---|
| 直接回答 | PASS | 模型无工具调用并返回完整最终答案。 |
| Calculator | PASS | 模型自主调用 `calculator`，`(17*23)+5` 得到 `396`。 |
| 工具型追问 | PASS | 同一 session 基于上一轮结果再次调用 `calculator`，得到 `397`。 |
| Search → Todo | PASS | 模型按 `search`、`todo` 顺序执行；todo 已落盘；最终答案声明搜索结果为 Mock、非实时数据。 |

机器可读的脱敏结果位于本地 `acceptance/results/real_api_latest.json`。该目录被 Git 忽略，证据只记录执行时间、模型、场景状态和工具顺序，不记录 API Key、原始 `reasoning_content` 或回答正文。

## 安全检查

- `.env` 文件 mode 已收紧为 `0600`，并被 `.gitignore` 排除；
- 对当前 API Key 值扫描所有 Git 跟踪文件，命中数为 0；
- 冒烟测试数据库使用临时目录，退出后自动清理；
- 真实工具轮成功证明 DeepSeek thinking/tool-call 协议续传可用。

## 尚需人工完成

- 将当前工作区修改 commit 并 push 到代码仓库；
- 按 README 的录屏路径生成终端或网页操作录屏。

这两项属于外部发布材料，不影响代码级核心流程，但在提交 `TASK.md` 作业前仍必须完成。
