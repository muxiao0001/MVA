import json
import sqlite3

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-11 工具失败"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, model = env.app(
            [
                tool_response(
                    "call_zero",
                    "calculator",
                    '{"expression":"1/0"}',
                ),
                direct_response("不能除以零，计算未完成。"),
            ]
        )
        session = app.sessions.create("tool-failure")
        result = app.runtime.run(session.id, "计算 1/0")
        assert result.status == "succeeded"
        assert len(model.requests) == 2
        message = next(
            item for item in app.messages.load_after(session.id, 0)
            if item.role == "tool"
        )
        payload = json.loads(message.content or "{}")
        assert payload["ok"] is False
        assert payload["error"]["type"] == "invalid_expression"

        original_add = app.todos.add

        def fail_add(*args, **kwargs):
            raise sqlite3.OperationalError("injected storage failure")

        app.todos.add = fail_add  # type: ignore[method-assign]
        model.script.append(
            tool_response(
                "call_storage_fail",
                "todo",
                '{"operation":"add","content":"不会提交"}',
            )
        )
        storage_result = app.runtime.run(session.id, "注入存储失败")
        assert storage_result.status == "failed"
        assert storage_result.error_code == "storage_error"
        assert app.runs.get(storage_result.run_id)["context_valid"] == 0

        app.todos.add = original_add  # type: ignore[method-assign]
        model.script.append(direct_response("session 已恢复可用。"))
        recovered = app.runtime.run(session.id, "失败后继续")
        assert recovered.status == "succeeded"
        return "工具与存储异常均可控终止，失败后 session 仍可继续。"
    finally:
        env.close()
