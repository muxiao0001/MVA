from __future__ import annotations

import hashlib
import json
import time
import uuid

from ..context.builder import ContextBuilder
from ..context.compactor import ContextCompactor
from ..domain.models import (
    ModelRequest,
    ModelResponse,
    RunResult,
    ToolCall,
    ToolContext,
    ToolResult,
)
from ..errors import (
    ContextOverflowError,
    InputValidationError,
    MVAError,
    ModelOutputTruncatedError,
    ModelProtocolError,
    ModelResponseTooLargeError,
    StorageError,
    ToolBudgetExceededError,
)
from ..model.base import ModelClient
from ..observability.trace import TraceRecorder
from ..storage.database import Database
from ..storage.repositories import (
    MessageRepository,
    RunRepository,
    SessionRepository,
    SessionTodoStore,
    TodoRepository,
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
        todos: TodoRepository,
        context_builder: ContextBuilder,
        compactor: ContextCompactor,
        trace: TraceRecorder,
        max_user_input_chars: int,
        hard_context_token_limit: int,
        max_tool_calls_per_response: int,
        max_tool_calls_per_run: int,
        max_tool_arguments_chars: int,
        max_model_output_tokens: int,
        max_model_output_chars: int,
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
        self.todos = todos
        self.context_builder = context_builder
        self.compactor = compactor
        self.trace = trace
        self.max_user_input_chars = max_user_input_chars
        self.hard_context_token_limit = hard_context_token_limit
        self.max_tool_calls_per_response = max_tool_calls_per_response
        self.max_tool_calls_per_run = max_tool_calls_per_run
        self.max_tool_arguments_chars = max_tool_arguments_chars
        self.max_model_output_tokens = max_model_output_tokens
        self.max_model_output_chars = max_model_output_chars

    def run(self, session_id: str, user_input: str) -> RunResult:
        if not isinstance(user_input, str):
            raise InputValidationError("用户输入必须是文本")
        if not user_input.strip():
            raise InputValidationError("用户输入不能为空")
        if len(user_input) > self.max_user_input_chars:
            raise InputValidationError(
                f"用户输入超过 {self.max_user_input_chars} 字符上限"
            )
        self.sessions.get(session_id)

        run_id = f"run_{uuid.uuid4().hex[:16]}"
        summaries: list[str] = []
        step = 0
        pending_tool_chain = False
        total_tool_calls = 0

        try:
            recovered_runs = self.runs.recover_interrupted(session_id)
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
                payload={
                    "input_chars": len(user_input.strip()),
                    "recovered_interrupted_run_count": len(recovered_runs),
                },
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
                if context.estimated_tokens > self.hard_context_token_limit:
                    raise ContextOverflowError(
                        "Context 压缩后仍超过 hard token limit"
                    )
                request = ModelRequest(
                    model=self.model_name,
                    system_prompt=context.system_prompt,
                    messages=context.messages,
                    tools=self.registry.specs(),
                    thinking_enabled=self.thinking_enabled,
                    max_output_tokens=self.max_model_output_tokens,
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
                response_tool_calls = len(response.tool_calls)
                try:
                    self._validate_model_response(
                        response,
                        max_tool_arguments_chars=self.max_tool_arguments_chars,
                        max_model_output_chars=self.max_model_output_chars,
                    )
                    if response_tool_calls > self.max_tool_calls_per_response:
                        raise ToolBudgetExceededError(
                            "单次模型响应的工具调用数超过预算"
                        )
                    if (
                        total_tool_calls + response_tool_calls
                        > self.max_tool_calls_per_run
                    ):
                        raise ToolBudgetExceededError(
                            "本次 run 的工具调用总数超过预算"
                        )
                except MVAError as exc:
                    self.trace.emit(
                        run_id=run_id,
                        session_id=session_id,
                        step=step,
                        event_type="model_response",
                        status="rejected",
                        payload={
                            "finish_reason": self._safe_finish_reason(
                                response.finish_reason
                            ),
                            "tool_call_count": response_tool_calls,
                        },
                        duration_ms=duration_ms,
                        error_type=exc.code,
                    )
                    raise

                if response.tool_calls and step == self.max_steps:
                    self.trace.emit(
                        run_id=run_id,
                        session_id=session_id,
                        step=step,
                        event_type="model_response",
                        status="rejected",
                        payload={
                            "finish_reason": self._safe_finish_reason(
                                response.finish_reason
                            ),
                            "tool_call_count": response_tool_calls,
                            "reason": "max_steps_before_tool_execution",
                        },
                        duration_ms=duration_ms,
                        error_type="max_steps",
                    )
                    summaries.append(
                        decisions.tool_calls(
                            step,
                            [call.name for call in response.tool_calls],
                        )
                    )
                    summaries.append(decisions.max_steps(self.max_steps))
                    self._finish(
                        run_id=run_id,
                        session_id=session_id,
                        step_count=step,
                        status="max_steps",
                        stop_reason="max_steps",
                        error_code="max_steps",
                        context_valid=True,
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
                total_tool_calls += response_tool_calls
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
                context_valid=(
                    not pending_tool_chain
                    and exc.code != "context_overflow"
                ),
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
    def _validate_model_response(
        response: ModelResponse,
        *,
        max_tool_arguments_chars: int,
        max_model_output_chars: int,
    ) -> None:
        if response.finish_reason == "length":
            raise ModelOutputTruncatedError("模型回答因长度限制被截断")
        if response.tool_calls and response.finish_reason != "tool_calls":
            raise ModelProtocolError("工具响应的 finish_reason 非法")
        if not response.tool_calls and response.finish_reason != "stop":
            raise ModelProtocolError("最终回答的 finish_reason 非法")
        output_chars = (
            len(response.content or "")
            + len(response.reasoning_content or "")
            + sum(
                len(call.id) + len(call.name) + len(call.arguments)
                for call in response.tool_calls
            )
        )
        if output_chars > max_model_output_chars:
            raise ModelResponseTooLargeError("模型消息超过允许的字符上限")
        call_ids = [call.id for call in response.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ModelProtocolError("同一模型响应包含重复的 tool call ID")
        for call in response.tool_calls:
            if not call.id or not call.name or not isinstance(call.arguments, str):
                raise ModelProtocolError("模型工具调用结构非法")
            if len(call.arguments) > max_tool_arguments_chars:
                raise ToolBudgetExceededError("工具参数超过字符预算")
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
                    "usage": self._safe_usage(response.usage),
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
        call: ToolCall,
    ) -> ToolResult:
        started = time.perf_counter()
        with self.database.transaction() as connection:
            result = self.registry.invoke(
                call,
                ToolContext(
                    session_id=session_id,
                    run_id=run_id,
                    todo_store=(
                        SessionTodoStore(
                            self.todos,
                            session_id,
                            connection,
                        )
                        if call.name == "todo"
                        else None
                    ),
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
                    "tool_call_ref": hashlib.sha256(
                        call.id.encode("utf-8")
                    ).hexdigest()[:12],
                    "arguments_chars": len(call.arguments),
                    "result_chars": len(content),
                    "result_ok": result.ok,
                },
                duration_ms=duration_ms,
                error_type=result.error_type,
                connection=connection,
            )
        return result

    @staticmethod
    def _safe_finish_reason(finish_reason: str | None) -> str:
        if finish_reason in {"stop", "tool_calls", "length"}:
            return finish_reason
        return "invalid"

    @staticmethod
    def _safe_usage(usage: dict[str, object]) -> dict[str, int | float]:
        allowed = {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        }
        return {
            key: value
            for key, value in usage.items()
            if (
                key in allowed
                and not isinstance(value, bool)
                and isinstance(value, (int, float))
            )
        }

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
                session_id=session_id,
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
