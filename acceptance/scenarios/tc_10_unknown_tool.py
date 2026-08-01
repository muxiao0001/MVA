import json

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-10 未注册工具"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response("call_unknown", "shell", '{"command":"whoami"}'),
                direct_response("该工具未注册，无法执行。"),
            ]
        )
        session = app.sessions.create("unknown-tool")
        result = app.runtime.run(session.id, "调用未知工具")
        assert result.status == "succeeded"
        message = next(
            item for item in app.messages.load_after(session.id, 0)
            if item.role == "tool"
        )
        payload = json.loads(message.content or "{}")
        assert payload["error"]["type"] == "unknown_tool"
        events = app.traces.list(session_id=session.id, run_id=result.run_id)
        event = next(item for item in events if item["event_type"] == "tool_execution")
        assert event["error_type"] == "unknown_tool"
        return "白名单拒绝未知工具，trace 记录 unknown_tool。"
    finally:
        env.close()

