from acceptance.fixtures import ScenarioEnvironment, direct_response

NAME = "TC-01 直接回答"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, model = env.app([direct_response("巴黎是法国首都。")])
        session = app.sessions.create("direct")
        result = app.runtime.run(session.id, "法国首都是什么？")
        assert result.status == "succeeded"
        assert result.answer == "巴黎是法国首都。"
        assert len(model.requests) == 1
        assert {item["function"]["name"] for item in model.requests[0].tools} == {
            "calculator",
            "search",
            "todo",
        }
        events = app.traces.list(session_id=session.id, run_id=result.run_id)
        assert not any(event["event_type"] == "tool_execution" for event in events)
        return "直接回答成功，且未执行工具。"
    finally:
        env.close()

