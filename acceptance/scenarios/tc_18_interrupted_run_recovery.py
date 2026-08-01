import json

from mva.domain.models import ToolCall

from acceptance.fixtures import ScenarioEnvironment, direct_response

NAME = "TC-18 中断 Run 恢复"


def _create_stale_run(app, session_id: str, run_id: str, stage: str) -> None:
    app.runs.start_with_user_message(
        run_id=run_id,
        session_id=session_id,
        user_input=f"stale at {stage}",
        messages=app.messages,
        sessions=app.runtime.sessions,
    )
    if stage == "user_only":
        return
    call = ToolCall(
        id=f"call_{stage}",
        name="todo" if stage == "tool_result" else "calculator",
        arguments=(
            '{"operation":"add","content":"中断前已提交的待办"}'
            if stage == "tool_result"
            else '{"expression":"1+1"}'
        ),
    )
    with app.database.transaction() as connection:
        app.messages.append(
            session_id=session_id,
            run_id=run_id,
            role="assistant",
            content="",
            reasoning_content="private-stale-reasoning",
            tool_calls=(call,),
            connection=connection,
        )
        if stage == "tool_result":
            app.todos.add(
                session_id,
                "中断前已提交的待办",
                call.id,
                connection=connection,
            )
            app.messages.append(
                session_id=session_id,
                run_id=run_id,
                role="tool",
                content=json.dumps(
                    {
                        "ok": True,
                        "output": {
                            "created": True,
                            "content": "中断前已提交的待办",
                        },
                    }
                ),
                tool_call_id=call.id,
                tool_name=call.name,
                connection=connection,
            )


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, _ = env.app(
            [
                direct_response("user-only 中断后已恢复。"),
                direct_response("tool-call 中断后已恢复。"),
                direct_response("tool-result 中断后已恢复。"),
            ]
        )
        for index, stage in enumerate(
            ("user_only", "tool_call", "tool_result"),
            start=1,
        ):
            session = app.sessions.create(stage)
            stale_run_id = f"run_stale_{index}"
            _create_stale_run(app, session.id, stale_run_id, stage)

            result = app.runtime.run(session.id, "中断后继续对话")
            assert result.status == "succeeded"
            stale = app.runs.get(session.id, stale_run_id)
            assert stale["status"] == "failed"
            assert stale["stop_reason"] == "interrupted"
            assert stale["context_valid"] == 0
            if stage == "tool_result":
                todos = app.todos.list(session.id)
                assert [todo.content for todo in todos] == [
                    "中断前已提交的待办"
                ]
            events = app.traces.list(
                session_id=session.id,
                run_id=result.run_id,
            )
            assert events[0]["payload"]["recovered_interrupted_run_count"] == 1

        return "三个中断点均被隔离，后续 run 可正常完成。"
    finally:
        env.close()
