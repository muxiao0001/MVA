import json
import urllib.request

from mva.domain.models import ModelRequest, ModelResponse, ToolCall
from mva.errors import (
    InputValidationError,
    ModelResponseTooLargeError,
)
from mva.model.deepseek import DeepSeekClient

from acceptance.fixtures import ScenarioEnvironment, direct_response

NAME = "TC-20 预算与终止语义"


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self.body
        return self.body[:size]


def run() -> str:
    oversized_env = ScenarioEnvironment()
    try:
        app, model = oversized_env.app(
            [direct_response("不应被调用")],
            max_user_input_chars=10,
        )
        session = app.sessions.create("input-budget")
        try:
            app.runtime.run(session.id, "x" * 11)
        except InputValidationError:
            pass
        else:
            raise AssertionError("超长用户输入未被拒绝")
        assert not model.requests
    finally:
        oversized_env.close()

    tool_env = ScenarioEnvironment()
    try:
        calls = tuple(
            ToolCall(
                id=f"call_budget_{index}",
                name="calculator",
                arguments='{"expression":"1+1"}',
            )
            for index in range(5)
        )
        app, _ = tool_env.app(
            [
                ModelResponse(
                    content="",
                    reasoning_content="private",
                    tool_calls=calls,
                    finish_reason="tool_calls",
                )
            ],
            max_tool_calls_per_response=4,
        )
        session = app.sessions.create("tool-budget")
        result = app.runtime.run(session.id, "触发过多工具调用")
        assert result.status == "failed"
        assert result.error_code == "tool_budget_exceeded"
        events = app.traces.list(
            session_id=session.id,
            run_id=result.run_id,
        )
        assert not any(event["event_type"] == "tool_execution" for event in events)
    finally:
        tool_env.close()

    run_tool_env = ScenarioEnvironment()
    try:
        first_calls = tuple(
            ToolCall(
                id=f"call_run_first_{index}",
                name="calculator",
                arguments='{"expression":"1+1"}',
            )
            for index in range(2)
        )
        second_calls = tuple(
            ToolCall(
                id=f"call_run_second_{index}",
                name="calculator",
                arguments='{"expression":"2+2"}',
            )
            for index in range(2)
        )
        app, _ = run_tool_env.app(
            [
                ModelResponse(
                    content="",
                    reasoning_content="private-1",
                    tool_calls=first_calls,
                    finish_reason="tool_calls",
                ),
                ModelResponse(
                    content="",
                    reasoning_content="private-2",
                    tool_calls=second_calls,
                    finish_reason="tool_calls",
                ),
            ],
            max_tool_calls_per_response=2,
            max_tool_calls_per_run=3,
        )
        session = app.sessions.create("run-tool-budget")
        result = app.runtime.run(session.id, "触发 run 工具总预算")
        assert result.status == "failed"
        assert result.error_code == "tool_budget_exceeded"
        events = app.traces.list(
            session_id=session.id,
            run_id=result.run_id,
        )
        tool_events = [
            event for event in events
            if event["event_type"] == "tool_execution"
        ]
        assert len(tool_events) == 2
    finally:
        run_tool_env.close()

    argument_env = ScenarioEnvironment()
    try:
        app, _ = argument_env.app(
            [
                ModelResponse(
                    content="",
                    reasoning_content="private",
                    tool_calls=(
                        ToolCall(
                            id="call_argument_budget",
                            name="calculator",
                            arguments='{"expression":"123456789"}',
                        ),
                    ),
                    finish_reason="tool_calls",
                )
            ],
            max_tool_arguments_chars=10,
        )
        session = app.sessions.create("argument-budget")
        result = app.runtime.run(session.id, "触发工具参数预算")
        assert result.status == "failed"
        assert result.error_code == "tool_budget_exceeded"
        events = app.traces.list(
            session_id=session.id,
            run_id=result.run_id,
        )
        assert not any(
            event["event_type"] == "tool_execution" for event in events
        )
    finally:
        argument_env.close()

    context_env = ScenarioEnvironment()
    try:
        app, model = context_env.app(
            [direct_response("不应被调用")],
            context_token_threshold=100,
            hard_context_token_limit=100,
        )
        session = app.sessions.create("context-budget")
        result = app.runtime.run(session.id, "触发 hard context limit")
        assert result.status == "failed"
        assert result.error_code == "context_overflow"
        assert not model.requests
    finally:
        context_env.close()

    truncated_env = ScenarioEnvironment()
    try:
        app, _ = truncated_env.app(
            [
                ModelResponse(
                    content="partial answer",
                    reasoning_content=None,
                    tool_calls=(),
                    finish_reason="length",
                )
            ]
        )
        session = app.sessions.create("truncated")
        result = app.runtime.run(session.id, "请求长回答")
        assert result.status == "failed"
        assert result.error_code == "model_output_truncated"
        assert result.answer is None
    finally:
        truncated_env.close()

    output_env = ScenarioEnvironment()
    try:
        app, _ = output_env.app(
            [direct_response("回答内容超过字符硬限制")],
            max_model_output_chars=5,
        )
        session = app.sessions.create("model-output-budget")
        result = app.runtime.run(session.id, "触发模型字符预算")
        assert result.status == "failed"
        assert result.error_code == "model_response_too_large"
        assert result.answer is None
    finally:
        output_env.close()

    captured: dict[str, object] = {}
    original_urlopen = urllib.request.urlopen

    def oversized_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(b"x" * 1_025)

    try:
        urllib.request.urlopen = oversized_urlopen
        client = DeepSeekClient(
            api_key="acceptance-key",
            base_url="https://api.deepseek.com",
            max_retries=0,
            max_response_bytes=1_024,
        )
        request = ModelRequest(
            model="deepseek-v4-flash",
            system_prompt="system",
            messages=({"role": "user", "content": "hello"},),
            tools=(),
            max_output_tokens=321,
        )
        try:
            client.complete(request)
        except ModelResponseTooLargeError:
            pass
        else:
            raise AssertionError("超大 HTTP 响应未被拒绝")
        assert captured["payload"]["max_tokens"] == 321
    finally:
        urllib.request.urlopen = original_urlopen

    return "输入、context、工具、HTTP 响应和截断终止均受硬预算控制。"
