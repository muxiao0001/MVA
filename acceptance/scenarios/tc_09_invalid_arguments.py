import json

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
        return "Schema 拒绝错误类型，失败结果回传模型后有限结束。"
    finally:
        env.close()

