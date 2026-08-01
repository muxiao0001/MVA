from acceptance.fixtures import ScenarioEnvironment, tool_response

NAME = "TC-13 最大轮次"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, model = env.app(
            [
                tool_response(
                    f"call_loop_{index}",
                    "calculator",
                    '{"expression":"1+1"}',
                )
                for index in range(3)
            ],
            max_steps=3,
        )
        session = app.sessions.create("max-steps")
        result = app.runtime.run(session.id, "永远继续调用工具")
        assert result.status == "max_steps"
        assert result.stop_reason == "max_steps"
        assert len(model.requests) == 3
        stored = app.runs.get(session.id, result.run_id)
        assert stored["status"] == "max_steps"
        assert stored["step_count"] == 3
        tool_events = [
            event
            for event in app.traces.list(
                session_id=session.id,
                run_id=result.run_id,
            )
            if event["event_type"] == "tool_execution"
        ]
        assert len(tool_events) == 2
        return "第 3 次模型调用后硬停止，最后一步工具未执行。"
    finally:
        env.close()
