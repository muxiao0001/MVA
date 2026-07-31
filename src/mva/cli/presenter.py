from __future__ import annotations

import json
from collections.abc import Iterable

from ..domain.models import RunResult, Session

_ERROR_HINTS = {
    "configuration_error": "配置不完整，请检查 DEEPSEEK_API_KEY 与运行参数。",
    "model_authentication_error": "模型鉴权失败，请检查 API Key。",
    "model_balance_error": "模型账户余额不足，本次任务未完成。",
    "model_rate_limit_error": "模型请求频率受限，请稍后重试。",
    "model_service_error": "模型服务暂时不可用，请稍后重试。",
    "model_request_error": "模型拒绝了请求，请检查模型名与 Base URL。",
    "model_protocol_error": "模型返回格式异常，本次任务已安全终止。",
    "storage_error": "本地存储失败，请检查数据库路径与文件权限。",
    "max_steps": "达到轮次上限，本次任务未完成。",
    "internal_error": "发生未预期错误；可通过 trace 定位。",
}


def present_run(result: RunResult) -> str:
    lines = [f"[run {result.run_id}]"]
    lines.extend(f"[决策] {item}" for item in result.decision_summaries)
    if result.answer is not None:
        lines.append(result.answer)
    else:
        hint = _ERROR_HINTS.get(
            result.error_code or "",
            f"任务未完成：{result.stop_reason}",
        )
        lines.append(f"[错误] {hint}")
    return "\n".join(lines)


def present_sessions(sessions: Iterable[Session]) -> str:
    items = list(sessions)
    if not items:
        return "暂无可恢复 session。"
    lines = ["SESSION_ID        UPDATED                         TITLE"]
    for session in items:
        title = session.title or "-"
        lines.append(f"{session.id:<17} {session.updated_at:<31} {title}")
    return "\n".join(lines)


def present_traces(events: list[dict]) -> str:
    if not events:
        return "没有匹配的 trace。"
    return "\n".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True)
        for event in events
    )

