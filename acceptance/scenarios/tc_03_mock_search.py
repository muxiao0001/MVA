import json

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-03 Mock 搜索"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response(
                    "call_search",
                    "search",
                    '{"query":"Agent context 压缩","limit":2}',
                ),
                direct_response("以下结论来自固定 Mock 搜索数据，并非实时联网结果。"),
            ]
        )
        session = app.sessions.create("search")
        result = app.runtime.run(session.id, "搜索 Agent context 压缩")
        assert result.status == "succeeded"
        message = next(
            item for item in app.messages.load_after(session.id, 0)
            if item.role == "tool"
        )
        output = json.loads(message.content or "{}")["output"]
        assert output["source"] == "mock"
        assert "不是实时联网" in output["notice"]
        assert output["results"]
        return "search 返回稳定 Mock 数据并显式标注非实时。"
    finally:
        env.close()

