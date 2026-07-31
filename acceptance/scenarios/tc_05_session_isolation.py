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
                ),
                direct_response("A 已记录。"),
                tool_response(
                    "call_b",
                    "todo",
                    '{"operation":"add","content":"B 窗口周报待办"}',
                ),
                direct_response("B 已记录。"),
            ]
        )
        session_a = app.sessions.create("A")
        session_b = app.sessions.create("B")
        assert app.runtime.run(session_a.id, "记录 A 待办").status == "succeeded"
        assert app.runtime.run(session_b.id, "记录 B 待办").status == "succeeded"
        assert [todo.content for todo in app.todos.list(session_a.id)] == [
            "A 窗口天气待办"
        ]
        assert [todo.content for todo in app.todos.list(session_b.id)] == [
            "B 窗口周报待办"
        ]
        assert all(
            message.session_id == session_a.id
            for message in app.messages.load_after(session_a.id, 0)
        )
        assert all(
            message.session_id == session_b.id
            for message in app.messages.load_after(session_b.id, 0)
        )
        return "两个 session 的消息与 todo 均独立。"
    finally:
        env.close()

