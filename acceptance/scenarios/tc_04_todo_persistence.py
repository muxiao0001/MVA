import json

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-04 Todo 持久化"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        first, _ = env.app(
            [
                tool_response(
                    "call_add",
                    "todo",
                    '{"operation":"add","content":"周五提交周报"}',
                ),
                direct_response("已新增待办。"),
            ]
        )
        session = first.sessions.create("todo-persist")
        added = first.runtime.run(session.id, "记下周五提交周报")
        assert added.status == "succeeded"

        restarted, _ = env.app(
            [
                tool_response("call_list", "todo", '{"operation":"list"}'),
                direct_response("当前有一项待办：周五提交周报。"),
            ]
        )
        listed = restarted.runtime.run(session.id, "查看待办")
        assert listed.status == "succeeded"
        todos = restarted.todos.list(session.id)
        assert [todo.content for todo in todos] == ["周五提交周报"]
        tool_messages = [
            message
            for message in restarted.messages.load_after(session.id, 0)
            if message.role == "tool" and message.tool_name == "todo"
        ]
        latest = json.loads(tool_messages[-1].content or "{}")
        assert latest["output"]["count"] == 1
        return "进程级重建后仍可读取同一 session 的待办。"
    finally:
        env.close()

