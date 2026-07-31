from acceptance.fixtures import ScenarioEnvironment, direct_response

NAME = "TC-14 Context 压缩"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, model = env.app(
            [direct_response(f"已记住事实 {index}。") for index in range(6)],
            context_token_threshold=100,
            context_retain_runs=2,
        )
        session = app.sessions.create("compaction")
        for index in range(6):
            result = app.runtime.run(
                session.id,
                f"事实 {index}：我的长期代号是蓝鲸-{index}，请记住这段信息。",
            )
            assert result.status == "succeeded"

        restored = app.sessions.get(session.id)
        assert restored.compacted_through_seq > 0
        assert restored.summary
        assert "蓝鲸-0" in restored.summary
        assert any(
            "<session_summary>" in request.system_prompt
            for request in model.requests
        )
        events = app.traces.list(session_id=session.id)
        assert any(event["event_type"] == "context_compacted" for event in events)
        return (
            f"压缩游标推进到 seq={restored.compacted_through_seq}，"
            "早期事实进入滚动摘要。"
        )
    finally:
        env.close()

