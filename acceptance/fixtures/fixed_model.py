from __future__ import annotations

from collections.abc import Callable, Iterable

from mva.domain.models import ModelRequest, ModelResponse, ToolCall

ScriptItem = ModelResponse | Exception | Callable[[ModelRequest], ModelResponse]


class FixedModelClient:
    """Deterministic model replacement used only by acceptance scenarios."""

    def __init__(self, script: Iterable[ScriptItem]) -> None:
        self.script = list(script)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.script:
            raise AssertionError("FixedModelClient response queue is empty")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item


def direct_response(
    content: str,
    *,
    reasoning_content: str | None = None,
) -> ModelResponse:
    return ModelResponse(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=(),
        finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


def tool_response(
    call_id: str,
    name: str,
    arguments: str,
    *,
    content: str | None = None,
    reasoning_content: str | None = "internal-test-reasoning",
) -> ModelResponse:
    return ModelResponse(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=(ToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason="tool_calls",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )

