from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, load_prompt
from .context.builder import ContextBuilder
from .context.compactor import ContextCompactor
from .model.base import ModelClient
from .model.deepseek import DeepSeekClient
from .observability.redaction import Redactor
from .observability.trace import TraceRecorder
from .runtime.agent import AgentRuntime
from .session.service import SessionService
from .storage.database import Database
from .storage.repositories import (
    MessageRepository,
    RunRepository,
    SessionRepository,
    TodoRepository,
    TraceRepository,
)
from .tools import CalculatorTool, MockSearchTool, TodoTool, ToolRegistry


@dataclass(frozen=True)
class Application:
    settings: Settings
    database: Database
    sessions: SessionService
    runtime: AgentRuntime
    todos: TodoRepository
    traces: TraceRecorder
    messages: MessageRepository
    runs: RunRepository
    registry: ToolRegistry


def build_application(
    settings: Settings,
    *,
    model_client: ModelClient | None = None,
    system_prompt: str | None = None,
) -> Application:
    settings.validate()
    database = Database(settings.database_path)
    database.initialize()

    session_repository = SessionRepository(database)
    message_repository = MessageRepository(database)
    run_repository = RunRepository(database)
    todo_repository = TodoRepository(database)
    trace_repository = TraceRepository(database)

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(MockSearchTool())
    registry.register(TodoTool())

    context_builder = ContextBuilder(
        sessions=session_repository,
        messages=message_repository,
        base_system_prompt=system_prompt or load_prompt("agent_system.md"),
        tool_count=len(registry.names()),
    )
    compactor = ContextCompactor(
        database=database,
        sessions=session_repository,
        messages=message_repository,
        context_builder=context_builder,
        token_threshold=settings.context_token_threshold,
        retain_recent_runs=settings.context_retain_runs,
    )
    resolved_model_client = model_client or DeepSeekClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.model_timeout_seconds,
        max_retries=settings.api_max_retries,
        retry_base_seconds=settings.api_retry_base_seconds,
        allow_custom_base_url=settings.allow_custom_base_url,
        max_response_bytes=settings.max_http_response_bytes,
    )
    trace = TraceRecorder(trace_repository, Redactor())
    runtime = AgentRuntime(
        database=database,
        model_client=resolved_model_client,
        model_name=settings.model,
        thinking_enabled=settings.thinking_enabled,
        max_steps=settings.max_steps,
        registry=registry,
        sessions=session_repository,
        messages=message_repository,
        runs=run_repository,
        todos=todo_repository,
        context_builder=context_builder,
        compactor=compactor,
        trace=trace,
        max_user_input_chars=settings.max_user_input_chars,
        hard_context_token_limit=settings.hard_context_token_limit,
        max_tool_calls_per_response=settings.max_tool_calls_per_response,
        max_tool_calls_per_run=settings.max_tool_calls_per_run,
        max_tool_arguments_chars=settings.max_tool_arguments_chars,
        max_model_output_tokens=settings.max_model_output_tokens,
        max_model_output_chars=settings.max_model_output_chars,
    )
    return Application(
        settings=settings,
        database=database,
        sessions=SessionService(session_repository),
        runtime=runtime,
        todos=todo_repository,
        traces=trace,
        messages=message_repository,
        runs=run_repository,
        registry=registry,
    )
