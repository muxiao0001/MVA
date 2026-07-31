from __future__ import annotations

import json
import time
import uuid
from typing import Any

from ..context.builder import ContextBuilder
from ..context.compactor import ContextCompactor
from ..domain.models import (
    ModelRequest,
    ModelResponse,
    RunResult,
    ToolContext,
    ToolResult,
)
from ..errors import MVAError, ModelProtocolError, StorageError
from ..model.base import ModelClient
from ..observability.trace import TraceRecorder
from ..storage.database import Database
from ..storage.repositories import (
    MessageRepository,
    RunRepository,
    SessionRepository,
)
from ..tools.registry import ToolRegistry
from . import decisions


class AgentRuntime:
    def __init__(
        self,
        *,
        database: Database,
        model_client: ModelClient,
        model_name: str,
        thinking_enabled: bool,
        max_steps: int,
        registry: ToolRegistry,
        sessions: SessionRepository,
        messages: MessageRepository,
        runs: RunRepository,
        context_builder: ContextBuilder,
        compactor: ContextCompactor,
        trace: TraceRecorder,
    ) -> None:
        self.database = database
        self.model_client = model_client
        self.model_name = model_name
        self.thinking_enabled = thinking_enabled
        self.max_steps = max_steps
        self.registry = registry
        self.sessions = sessions
        self.messages = messages
        self.runs = runs
        self.context_builder = context_builder
        self.compactor = compactor
        self.trace = trace

    def run(self, session_id: str, user_input: str) -> RunResult:
        if not user_input.strip():
            raise ValueError("用户输入不能为空")
        self.sessions.get(session_id)

        run_id = f"run_{uuid.uuid4().hex[:16]}"
        summaries: list[str] = []
        step = 0
        pending_tool_chain = False

        try:
            self.runs.start_with_user_message(
                run_id=run_id,
                session_id=session_id,
                user_input=user_input.strip(),
                messages=self.messages,
                sessions=self.sessions,
            )
            self.trace.emit(
                run_id=run_id,
                session_id=session_id,
                step=0,
                event_type="run_start",
                status="ok",
                payload={"input_chars": len(user_input.strip())},
            )

            compaction = self.compactor.compact_if_needed(session_id)
            if compaction.compacted:
                self.trace.emit(
                    run_id=run_id,
                    session_id=session_id,
                    step=0,
                    event_type="context_compacted",
                    status="ok",
                    payload={
                        "before_tokens": compaction.before_tokens,
                        "after_tokens": compaction.after_tokens,
                        "compacted_through_seq": compaction.compacted_through_seq,
                        "reason": compaction.reason,
                    },
                )

            for step in range(1, self.max_steps + 1):
                context = self.context_builder.build(session_id)
                request = ModelRequest(
                    model=self.model_name,
                    system_prompt=context.system_prompt,
                    messages=context.messages,
                    tools=self.registry.specs(),
                    thinking_enabled=self.thinking_enabled,
                )
                self.trace.emit(
                    run_id=run_id,
                    session_id=session_id,
                    step=step,
                    event_type="model_request",
                    status="started",
                    payload={
                        "message_count": len(request.messages),
                        "estimated_tokens": context.estimated_tokens,
                        "tools": list(self.registry.names()),
                    },
                )

                started = time.perf_counter()
                try:
                    response = self.model_client.complete(request)
                except MVAError as exc:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    self.trace.emit(
                        run_id=run_id,
                        session_id=session_id,
                        step=step,
                        event_type="model_response",
                        status="error",
                        payload={"finish_reason": None, "tool_call_count": 0},
                        duration_ms=duration_ms,
                        error_type=exc.code,
                    )
                    raise
                duration_ms = int((time.perf_counter() - started) * 1000)
                self._validate_model_response(response)
                self._persist_model_response(
                    session_id=session_id,
                    run_id=run_id,
                    step=step,
                    response=response,
                    duration_ms=duration_ms,
                )

                if not response.tool_calls:
                    answer = (response.content or "").strip()
                    if not answer:
                        raise ModelProtocolError("模型返回了空答案")
                    summaries.append(decisions.direct_answer(step))
                    self._finish(
                        run_id=run_id,
                        session_id=session_id,
                        step_count=step,
                        status="succeeded",
                        stop_reason="final_answer",
                        error_code=None,
                        context_valid=True,
                    )
                    return RunResult(
                        status="succeeded",
                        run_id=run_id,
                        session_id=session_id,
                        answer=answer,
                        stop_reason="final_answer",
                        decision_summaries=tuple(summaries),
                    )

                summaries.append(
                    decisions.tool_calls(
                        step,
                        [call.name for call in response.tool_calls],
                    )
                )
                pending_tool_chain = True
                for call in response.tool_calls:
                    result = self._execute_and_persist_tool(
                        session_id=session_id,
                        run_id=run_id,
                        step=step,
                        call=call,
                    )
                    summaries.append(decisions.tool_result(call.name, result.ok))
                pending_tool_chain = False

            summary = decisions.max_steps(self.max_steps)
            summaries.append(summary)
            self._finish(
                run_id=run_id,
                session_id=session_id,
                step_count=self.max_steps,
                status="max_steps",
                stop_reason="max_steps",
                error_code="max_steps",
                context_valid=not pending_tool_chain,
            )
            return RunResult(
                status="max_steps",
                run_id=run_id,
                session_id=session_id,
                answer=None,
                stop_reason="max_steps",
                decision_summaries=tuple(summaries),
                error_code="max_steps",
            )
        except MVAError as exc:
            summaries.append(decisions.failure(exc.code))
            self._finish_failure_best_effort(
                run_id=run_id,
                session_id=session_id,
                step_count=step,
                error=exc,
                context_valid=not pending_tool_chain,
            )
            return RunResult(
                status="failed",
                run_id=run_id,
                session_id=session_id,
                answer=None,
                stop_reason=exc.code,
                decision_summaries=tuple(summaries),
                error_code=exc.code,
            )
        except Exception as exc:
            error = MVAError(
                "Agent 发生未预期错误",
                detail=type(exc).__name__,
            )
            error.code = "internal_error"
            summaries.append(decisions.failure(error.code))
            self._finish_failure_best_effort(
                run_id=run_id,
                session_id=session_id,
                step_count=step,
                error=error,
                context_valid=not pending_tool_chain,
            )
            return RunResult(
                status="failed",
                run_id=run_id,
                session_id=session_id,
                answer=None,
                stop_reason=error.code,
                decision_summaries=tuple(summaries),
                error_code=error.code,
            )

    @staticmethod
    def _validate_model_response(response: ModelResponse) -> None:
        call_ids = [call.id for call in response.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ModelProtocolError("同一模型响应包含重复的 tool call ID")
        for call in response.tool_calls:
            if not call.id or not call.name or not isinstance(call.arguments, str):
                raise ModelProtocolError("模型工具调用结构非法")
        if not response.tool_calls and not (response.content or "").strip():
            raise ModelProtocolError("模型既未返回答案，也未返回工具调用")

    def _persist_model_response(
        self,
        *,
        session_id: str,
        run_id: str,
        step: int,
        response: ModelResponse,
        duration_ms: int,
    ) -> None:
        with self.database.transaction() as connection:
            self.messages.append(
                session_id=session_id,
                run_id=run_id,
                role="assistant",
                content=response.content,
                reasoning_content=(
                    response.reasoning_content if response.tool_calls else None
                ),
                tool_calls=response.tool_calls,
                connection=connection,
            )
            self.trace.emit(
                run_id=run_id,
                session_id=session_id,
                step=step,
                event_type="model_response",
                status="ok",
                payload={
                    "finish_reason": response.finish_reason,
                    "tool_call_count": len(response.tool_calls),
                    "has_content": bool(response.content),
                    "usage": response.usage,
                },
                duration_ms=duration_ms,
                connection=connection,
            )

    def _execute_and_persist_tool(
        self,
        *,
        session_id: str,
        run_id: str,
        step: int,
        call: Any,
    ) -> ToolResult:
        started = time.perf_counter()
        with self.database.transaction() as connection:
            result = self.registry.invoke(
                call,
                ToolContext(
                    session_id=session_id,
                    run_id=run_id,
                    connection=connection,
                ),
            )
            content = json.dumps(
                result.as_model_payload(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.messages.append(
                session_id=session_id,
                run_id=run_id,
                role="tool",
                content=content,
                tool_call_id=call.id,
                tool_name=call.name,
                connection=connection,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.trace.emit(
                run_id=run_id,
                session_id=session_id,
                step=step,
                event_type="tool_execution",
                status="ok" if result.ok else "error",
                payload={
                    "tool_name": call.name,
                    "tool_call_id": call.id,
                    "arguments": call.arguments,
                    "result": result.as_model_payload(),
                },
                duration_ms=duration_ms,
                error_type=result.error_type,
                connection=connection,
            )
        return result

    def _finish(
        self,
        *,
        run_id: str,
        session_id: str,
        step_count: int,
        status: str,
        stop_reason: str,
        error_code: str | None,
        context_valid: bool,
    ) -> None:
        with self.database.transaction() as connection:
            self.runs.finish(
                run_id=run_id,
                status=status,
                step_count=step_count,
                stop_reason=stop_reason,
                error_code=error_code,
                context_valid=context_valid,
                connection=connection,
            )
            self.trace.emit(
                run_id=run_id,
                session_id=session_id,
                step=step_count,
                event_type="run_end",
                status=status,
                payload={"stop_reason": stop_reason},
                error_type=error_code,
                connection=connection,
            )

    def _finish_failure_best_effort(
        self,
        *,
        run_id: str,
        session_id: str,
        step_count: int,
        error: MVAError,
        context_valid: bool,
    ) -> None:
        try:
            self._finish(
                run_id=run_id,
                session_id=session_id,
                step_count=step_count,
                status="failed",
                stop_reason=error.code,
                error_code=error.code,
                context_valid=context_valid,
            )
        except StorageError:
            # The original classified failure remains the user-facing result.
            pass
