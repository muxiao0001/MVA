from __future__ import annotations

import os
import sys
import tempfile
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
        settings = Settings(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            database_path=Path(directory) / "agent.db",
            max_steps=8,
            context_token_threshold=12_000,
            context_retain_runs=4,
            api_max_retries=2,
            api_retry_base_seconds=1.2,
            model_timeout_seconds=90,
            thinking_enabled=True,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

