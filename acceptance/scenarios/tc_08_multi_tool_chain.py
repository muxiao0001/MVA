from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-08 多工具链"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                tool_response(
                    "call_search_chain",
                    "search",
                    '{"query":"SQLite session"}',
                ),
                tool_response(
                    "call_todo_chain",
                    "todo",
                    '{"operation":"add","content":"阅读 SQLite session Mock 资料"}',
                ),
                direct_response("已根据 Mock 搜索结果新增阅读待办。"),
            ]
        )
        session = app.sessions.create("multi-tool")
        result = app.runtime.run(session.id, "搜索 SQLite session 并加入阅读待办")
        assert result.status == "succeeded"
        events = app.traces.list(session_id=session.id, run_id=result.run_id)
        names = [
            event["payload"]["tool_name"]
            for event in events
            if event["event_type"] == "tool_execution"
        ]
        assert names == ["search", "todo"]
        assert [todo.content for todo in app.todos.list(session.id)] == [
            "阅读 SQLite session Mock 资料"
        ]
        return "一次 run 顺序完成 search → todo → 最终回答。"
    finally:
        env.close()

