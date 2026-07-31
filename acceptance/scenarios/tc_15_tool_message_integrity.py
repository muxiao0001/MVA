from mva.domain.models import ModelRequest

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-15 工具消息完整性"


def _assert_pairs(request: ModelRequest):
    pending: set[str] = set()
    for message in request.messages:
        if message["role"] == "assistant":
            assert not pending
            pending = {
                call["id"]
                for call in message.get("tool_calls", [])
            }
        elif message["role"] == "tool":
            assert message["tool_call_id"] in pending
            pending.remove(message["tool_call_id"])
        else:
            assert not pending
    assert not pending
    return direct_response("恢复后的工具消息配对完整。")


def run() -> str:
    env = ScenarioEnvironment()
    try:
        first, _ = env.app(
            [
                tool_response(
                    "call_pair",
                    "calculator",
                    '{"expression":"20+22"}',
                ),
                direct_response("结果是 42。"),
                direct_response("第二轮用于形成压缩边界。"),
                direct_response("第三轮触发压缩。"),
            ],
            context_token_threshold=80,
            context_retain_runs=1,
        )
        session = first.sessions.create("pairing")
        assert first.runtime.run(session.id, "计算 20+22").status == "succeeded"
        assert first.runtime.run(session.id, "普通第二轮").status == "succeeded"
        assert first.runtime.run(session.id, "普通第三轮").status == "succeeded"

        restarted, _ = env.app(
            [_assert_pairs],
            context_token_threshold=80,
            context_retain_runs=1,
        )
        result = restarted.runtime.run(session.id, "重启后继续")
        assert result.status == "succeeded"
        return "压缩与重启后，所有 assistant tool_call / tool result 成对。"
    finally:
        env.close()

