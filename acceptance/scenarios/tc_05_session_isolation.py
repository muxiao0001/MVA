from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-05 Session 隔离"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response(
                    "call_a",
                    "todo",
                    '{"operation":"add","content":"A 窗口天气待办"}',
                    reasoning_content="private-reasoning-a",
                ),
                direct_response("A 已记录。"),
                tool_response(
                    "call_b",
                    "todo",
                    '{"operation":"add","content":"B 窗口周报待办"}',
                    reasoning_content="private-reasoning-b",
                ),
                direct_response("B 已记录。"),
            ]
        )
        session_a = app.sessions.create("A")
        session_b = app.sessions.create("B")
        result_a = app.runtime.run(session_a.id, "记录 A 待办")
        result_b = app.runtime.run(session_b.id, "记录 B 待办")
        assert result_a.status == "succeeded"
        assert result_b.status == "succeeded"
        assert [todo.content for todo in app.todos.list(session_a.id)] == [
            "A 窗口天气待办"
        ]
        assert [todo.content for todo in app.todos.list(session_b.id)] == [
            "B 窗口周报待办"
        ]
        messages_a = app.messages.load_after(session_a.id, 0)
        messages_b = app.messages.load_after(session_b.id, 0)
        assert all(message.session_id == session_a.id for message in messages_a)
        assert all(message.session_id == session_b.id for message in messages_b)
        assert any(
            message.reasoning_content == "private-reasoning-a"
            for message in messages_a
        )
        assert not any(
            message.reasoning_content == "private-reasoning-b"
            for message in messages_a
        )
        assert any(
            message.reasoning_content == "private-reasoning-b"
            for message in messages_b
        )
        assert not any(
            message.reasoning_content == "private-reasoning-a"
            for message in messages_b
        )

        traces_a = app.traces.list(session_id=session_a.id)
        traces_b = app.traces.list(session_id=session_b.id)
        assert traces_a and traces_b
        assert all(event["session_id"] == session_a.id for event in traces_a)
        assert all(event["session_id"] == session_b.id for event in traces_b)
        assert not app.traces.list(
            session_id=session_a.id,
            run_id=result_b.run_id,
        )
        assert not app.traces.list(
            session_id=session_b.id,
            run_id=result_a.run_id,
        )
        return "两个 session 的消息、内部推理、todo、run 与 trace 均独立。"
    finally:
        env.close()
