from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mva.bootstrap import build_application  # noqa: E402
from mva.config import Settings  # noqa: E402


def main() -> int:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("[SKIP] 未设置 DEEPSEEK_API_KEY，真实 API 冒烟测试安全跳过。")
        return 0

    with tempfile.TemporaryDirectory(prefix="mva-real-smoke-") as directory:
        settings = replace(
            Settings.from_env(),
            database_path=Path(directory) / "agent.db",
        )
        app = build_application(settings)
        session = app.sessions.create("real-api-smoke")

        direct = app.runtime.run(
            session.id,
            "请用一句中文说明你已准备好，只回答最终结论。",
        )
        if direct.status != "succeeded":
            print(f"[FAIL] 直接回答失败: {direct.error_code}")
            return 1
        print(f"[PASS] 直接回答: {direct.answer}")

        calculated = app.runtime.run(
            session.id,
            "请使用 calculator 工具计算 (17*23)+5，并报告结果。",
        )
        if calculated.status != "succeeded":
            print(f"[FAIL] 工具链失败: {calculated.error_code}")
            return 1
        events = app.traces.list(
            session_id=session.id,
            run_id=calculated.run_id,
        )
        used_calculator = any(
            event["event_type"] == "tool_execution"
            and event["payload"].get("tool_name") == "calculator"
            and event["status"] == "ok"
            for event in events
        )
        if not used_calculator:
            print("[FAIL] 模型未自主调用 calculator。")
            return 1
        print(f"[PASS] calculator 工具链: {calculated.answer}")

        follow_up = app.runtime.run(
            session.id,
            "基于刚才的计算结果，请再次使用 calculator 加 1，并报告结果。",
        )
        if follow_up.status != "succeeded":
            print(f"[FAIL] 工具型追问失败: {follow_up.error_code}")
            return 1
        follow_up_events = app.traces.list(
            session_id=session.id,
            run_id=follow_up.run_id,
        )
        if not any(
            event["event_type"] == "tool_execution"
            and event["payload"].get("tool_name") == "calculator"
            and event["status"] == "ok"
            for event in follow_up_events
        ):
            print("[FAIL] 工具型追问未再次自主调用 calculator。")
            return 1
        print(f"[PASS] 工具型追问: {follow_up.answer}")

        multi_tool = app.runtime.run(
            session.id,
            "请先使用 search 搜索 agent context 压缩，"
            "再把搜索结果第一条的标题加入 todo，最后说明结果来自 Mock 数据。",
        )
        if multi_tool.status != "succeeded":
            print(f"[FAIL] search → todo 多工具链失败: {multi_tool.error_code}")
            return 1
        multi_tool_events = app.traces.list(
            session_id=session.id,
            run_id=multi_tool.run_id,
        )
        tool_names = [
            event["payload"].get("tool_name")
            for event in multi_tool_events
            if event["event_type"] == "tool_execution"
            and event["status"] == "ok"
        ]
        if "search" not in tool_names or "todo" not in tool_names:
            print(f"[FAIL] 多工具链不完整: {tool_names}")
            return 1
        if tool_names.index("search") > tool_names.index("todo"):
            print(f"[FAIL] 多工具链顺序错误: {tool_names}")
            return 1
        if not app.todos.list(session.id):
            print("[FAIL] 多工具链未持久化 todo。")
            return 1
        answer = multi_tool.answer or ""
        if not any(marker in answer.casefold() for marker in ("mock", "模拟", "非实时")):
            print("[FAIL] 多工具链最终回答未声明 Mock 数据属性。")
            return 1
        print(f"[PASS] search → todo 多工具链: {multi_tool.answer}")

        evidence = {
            "executed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": settings.model,
            "base_url_host": "api.deepseek.com",
            "scenarios": {
                "direct_answer": "passed",
                "calculator": "passed",
                "tool_follow_up": "passed",
                "search_to_todo": "passed",
            },
            "multi_tool_order": tool_names,
            "api_key_recorded": False,
            "reasoning_content_recorded": False,
        }
        evidence_path = PROJECT_ROOT / "acceptance" / "results" / "real_api_latest.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[EVIDENCE] {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
