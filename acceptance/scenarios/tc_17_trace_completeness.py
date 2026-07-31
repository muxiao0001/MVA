from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-17 Trace 完整性"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response(
                    "call_trace",
                    "calculator",
                    '{"expression":"40+2"}',
                ),
                direct_response("42"),
            ]
        )
        session = app.sessions.create("trace")
        result = app.runtime.run(session.id, "计算 40+2")
        events = app.traces.list(session_id=session.id, run_id=result.run_id)
        event_types = [event["event_type"] for event in events]
        assert event_types == [
            "run_start",
            "model_request",
            "model_response",
            "tool_execution",
            "model_request",
            "model_response",
            "run_end",
        ]
        assert all(event["run_id"] == result.run_id for event in events)
        assert all(event["session_id"] == session.id for event in events)
        tool_event = next(
            event for event in events if event["event_type"] == "tool_execution"
        )
        assert tool_event["duration_ms"] is not None
        assert events[-1]["payload"]["stop_reason"] == "final_answer"
        return "run/session/step、工具、耗时和终止原因均可复盘。"
    finally:
        env.close()

