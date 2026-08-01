import json

from mva.domain.models import ToolCall, ToolContext

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-09 非法参数"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response(
                    "call_invalid",
                    "calculator",
                    '{"expression":42}',
                ),
                direct_response("工具参数类型错误，未执行计算。"),
            ]
        )
        session = app.sessions.create("invalid-args")
        result = app.runtime.run(session.id, "触发非法 calculator 参数")
        assert result.status == "succeeded"
        tool_message = next(
            message for message in app.messages.load_after(session.id, 0)
            if message.role == "tool"
        )
        payload = json.loads(tool_message.content or "{}")
        assert payload["ok"] is False
        assert payload["error"]["type"] == "tool_validation_error"

        for call in (
            ToolCall(
                id="call_nan",
                name="calculator",
                arguments='{"expression":NaN}',
            ),
            ToolCall(
                id="call_deep_json",
                name="calculator",
                arguments="[" * 1_100 + "]" * 1_100,
            ),
        ):
            rejected = app.registry.invoke(
                call,
                ToolContext(session_id=session.id, run_id=result.run_id),
            )
            assert rejected.ok is False
            assert rejected.error_type == "invalid_json"
        return "Schema、NaN 与过深 JSON 均被拒绝，并可控回传模型。"
    finally:
        env.close()
