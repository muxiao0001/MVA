import json

from mva.domain.models import ModelRequest

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-07 工具追问"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        def second_tool(request: ModelRequest):
            tool_payloads = [
                json.loads(item["content"])
                for item in request.messages
                if item["role"] == "tool"
            ]
            assert any(
                payload.get("output", {}).get("value") == 14
                for payload in tool_payloads
            )
            return tool_response(
                "call_double",
                "calculator",
                '{"expression":"14*2"}',
            )

        app, _ = env.app(
            [
                tool_response(
                    "call_first",
                    "calculator",
                    '{"expression":"7*2"}',
                ),
                direct_response("结果是 14。"),
                second_tool,
                direct_response("翻倍后是 28。"),
            ]
        )
        session = app.sessions.create("tool-followup")
        assert app.runtime.run(session.id, "7 乘 2 是多少？").status == "succeeded"
        result = app.runtime.run(session.id, "把刚才的结果翻倍")
        assert result.status == "succeeded"
        assert "28" in (result.answer or "")
        return "工具型追问看到了前一轮工具结果并再次调用工具。"
    finally:
        env.close()

