import json

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-02 计算工具"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response("call_calc", "calculator", '{"expression":"2+3*4"}'),
                direct_response("计算结果是 14。"),
            ]
        )
        session = app.sessions.create("calculator")
        result = app.runtime.run(session.id, "计算 2+3*4")
        assert result.status == "succeeded"
        messages = app.messages.load_after(session.id, 0)
        tool_message = next(message for message in messages if message.role == "tool")
        payload = json.loads(tool_message.content or "{}")
        assert payload["ok"] is True
        assert payload["output"]["value"] == 14
        return "calculator 自主调用成功，结果为 14。"
    finally:
        env.close()

