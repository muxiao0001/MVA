import json

from mva.cli.presenter import present_run
from mva.observability.redaction import Redactor

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-16 推理隐私"


def run() -> str:
    marker = "PRIVATE_REASONING_MARKER_7f31"
    env = ScenarioEnvironment()
    try:
        app, model = env.app(
            [
                tool_response(
                    "call_private",
                    "calculator",
                    '{"expression":"6*7"}',
                    reasoning_content=marker,
                ),
                direct_response("答案是 42。", reasoning_content=marker + "_final"),
            ]
        )
        session = app.sessions.create("privacy")
        result = app.runtime.run(session.id, "计算 6*7")
        assert result.status == "succeeded"
        trace_text = json.dumps(
            app.traces.list(session_id=session.id, run_id=result.run_id),
            ensure_ascii=False,
        )
        assert marker not in trace_text
        assert marker not in present_run(result)
        assert any(
            message.get("reasoning_content") == marker
            for message in model.requests[1].messages
            if message["role"] == "assistant"
        )
        stored = app.messages.load_after(session.id, 0)
        assert any(message.reasoning_content == marker for message in stored)
        assert not any(
            message.reasoning_content == marker + "_final"
            for message in stored
        )
        sanitized = Redactor().sanitize(
            {"arguments": '{"api_key":"secret-value","query":"safe"}'}
        )
        assert sanitized["arguments"]["api_key"] == "[REDACTED]"
        assert "secret-value" not in json.dumps(sanitized)
        return "私有推理仅在内部协议状态续传，CLI 与 trace 均不可见。"
    finally:
        env.close()
