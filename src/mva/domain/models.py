from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

RunStatus = Literal["running", "succeeded", "failed", "max_steps"]


@dataclass(frozen=True)
class Session:
    id: str
    title: str | None
    summary: str | None
    compacted_through_seq: int
    created_at: str
    updated_at: str
    status: str = "active"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class StoredMessage:
    id: int
    session_id: str
    run_id: str
    seq: int
    role: Literal["user", "assistant", "tool"]
    content: str | None
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system_prompt: str
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    thinking_enabled: bool = True


@dataclass(frozen=True)
class ModelResponse:
    content: str | None
    reasoning_content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]

    def as_api_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    run_id: str
    connection: sqlite3.Connection


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    tool_name: str
    ok: bool
    output: Any | None = None
    error_type: str | None = None
    error_message: str | None = None

    def as_model_payload(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "output": self.output}
        return {
            "ok": False,
            "error": {
                "type": self.error_type or "tool_error",
                "message": self.error_message or "工具执行失败",
            },
        }


@dataclass(frozen=True)
class Todo:
    id: str
    session_id: str
    content: str
    status: str
    created_at: str


@dataclass(frozen=True)
class TraceEvent:
    run_id: str
    session_id: str
    step: int
    event_type: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class RunResult:
    status: Literal["succeeded", "failed", "max_steps"]
    run_id: str
    session_id: str
    answer: str | None
    stop_reason: str
    decision_summaries: tuple[str, ...] = ()
    error_code: str | None = None


@dataclass(frozen=True)
class CompactionResult:
    compacted: bool
    before_tokens: int
    after_tokens: int
    compacted_through_seq: int
    reason: str | None = None

