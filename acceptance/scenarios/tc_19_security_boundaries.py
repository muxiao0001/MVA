import json
import stat
from typing import Any

from mva.cli.presenter import present_run, present_sessions, present_traces
from mva.domain.models import (
    ModelResponse,
    RunResult,
    Session,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from mva.errors import ConfigurationError, InputValidationError, StorageError
from mva.model.deepseek import DeepSeekClient
from mva.storage.database import Database
from mva.tools.base import Tool

from acceptance.fixtures import (
    ScenarioEnvironment,
    direct_response,
    tool_response,
)

NAME = "TC-19 安全边界"


class CapabilityProbeTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="capability_probe",
            description="Acceptance-only capability probe",
            parameters_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
        tool_call_id: str,
    ) -> ToolResult:
        assert arguments == {}
        assert not hasattr(context, "connection")
        assert context.todo_store is None
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.spec.name,
            ok=True,
            output={"scoped": True},
        )


def _assert_rejected_base_url(url: str) -> None:
    try:
        DeepSeekClient(api_key="secret", base_url=url)
    except ConfigurationError:
        return
    raise AssertionError(f"危险 Base URL 未被拒绝: {url}")


def run() -> str:
    env = ScenarioEnvironment()
    try:
        app, model = env.app(
            [
                tool_response("call_probe", "capability_probe", "{}"),
                direct_response("能力边界正常。"),
                tool_response(
                    "call_secret_todo",
                    "todo",
                    json.dumps(
                        {
                            "operation": "add",
                            "content": "DEEPSEEK_API_KEY=leaked-secret",
                        }
                    ),
                ),
                ModelResponse(
                    content="敏感待办已处理。",
                    reasoning_content=None,
                    tool_calls=(),
                    finish_reason="stop",
                    usage={
                        "total_tokens": 12,
                        "untrusted_text": "leaked-secret",
                    },
                ),
            ]
        )
        app.registry.register(CapabilityProbeTool())
        session = app.sessions.create("security-boundary")

        probe = app.runtime.run(session.id, "检查工具能力边界")
        assert probe.status == "succeeded"

        secret_run = app.runtime.run(session.id, "记录敏感字符串")
        assert secret_run.status == "succeeded"
        trace_text = json.dumps(
            app.traces.list(
                session_id=session.id,
                run_id=secret_run.run_id,
            ),
            ensure_ascii=False,
        )
        assert "leaked-secret" not in trace_text
        assert '"arguments"' not in trace_text
        assert '"result"' not in trace_text
        assert "untrusted_text" not in trace_text

        other_session = app.sessions.create("other")
        try:
            app.runs.get(other_session.id, secret_run.run_id)
        except StorageError:
            pass
        else:
            raise AssertionError("RunRepository 允许跨 session 读取")

        scoped_run_id = "run_finish_scope_probe"
        app.runs.start_with_user_message(
            run_id=scoped_run_id,
            session_id=session.id,
            user_input="验证 run 终态写入边界",
            messages=app.messages,
            sessions=app.runtime.sessions,
        )
        try:
            app.runs.finish(
                run_id=scoped_run_id,
                session_id=other_session.id,
                status="failed",
                step_count=0,
                stop_reason="scope_probe",
            )
        except StorageError:
            pass
        else:
            raise AssertionError("RunRepository 允许跨 session 写入终态")
        assert app.runs.get(session.id, scoped_run_id)["status"] == "running"
        app.runs.recover_interrupted(session.id)

        database_mode = stat.S_IMODE(env.database_path.stat().st_mode)
        assert database_mode == 0o600
        env.database_path.chmod(0o644)
        app.database.initialize()
        tightened_mode = stat.S_IMODE(env.database_path.stat().st_mode)
        assert tightened_mode == 0o600
        nested_database_path = env.root / "private" / "state" / "agent.db"
        Database(nested_database_path).initialize()
        assert stat.S_IMODE(
            nested_database_path.parent.parent.stat().st_mode
        ) == 0o700
        assert stat.S_IMODE(nested_database_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(nested_database_path.stat().st_mode) == 0o600

        _assert_rejected_base_url("http://api.deepseek.com")
        _assert_rejected_base_url("https://evil.example")
        custom = DeepSeekClient(
            api_key="secret",
            base_url="https://proxy.example",
            allow_custom_base_url=True,
        )
        assert custom.base_url == "https://proxy.example"

        for unsafe_title in ("danger\x1b[2J", "x" * 201):
            try:
                app.sessions.create(unsafe_title)
            except InputValidationError:
                pass
            else:
                raise AssertionError("不安全的 session 标题未被拒绝")

        rendered_run = present_run(
            RunResult(
                status="succeeded",
                run_id="run_safe",
                session_id=session.id,
                answer="answer\x1b[2J\x07",
                stop_reason="final_answer",
                decision_summaries=("decision\x1b]0;unsafe\x07",),
            )
        )
        rendered_sessions = present_sessions(
            [
                Session(
                    id=session.id,
                    title="title\x1b[2J",
                    summary=None,
                    compacted_through_seq=0,
                    created_at="now",
                    updated_at="now",
                )
            ]
        )
        rendered_traces = present_traces(
            [{"payload": {"text": "trace\x1b[2J\x07"}}]
        )
        assert not any(
            ord(character) < 32 and character not in {"\n", "\t"}
            for character in rendered_run + rendered_sessions + rendered_traces
        )
        assert len(model.requests) == 4
        return "最小工具能力、session 约束、秘密出站和文件权限均生效。"
    finally:
        env.close()
