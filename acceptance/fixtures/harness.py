from __future__ import annotations

import tempfile
from pathlib import Path

from mva.bootstrap import Application, build_application
from mva.config import Settings

from .fixed_model import FixedModelClient, ScriptItem


class ScenarioEnvironment:
    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="mva-acceptance-")
        self.root = Path(self._temporary.name)
        self.database_path = self.root / "agent.db"

    def close(self) -> None:
        self._temporary.cleanup()

    def app(
        self,
        script: list[ScriptItem],
        *,
        max_steps: int = 8,
        context_token_threshold: int = 12_000,
        context_retain_runs: int = 4,
        api_key: str | None = "acceptance-test-key",
        max_user_input_chars: int = 20_000,
        hard_context_token_limit: int = 64_000,
        max_tool_calls_per_response: int = 4,
        max_tool_calls_per_run: int = 8,
        max_tool_arguments_chars: int = 16_000,
        max_model_output_chars: int = 200_000,
        max_http_response_bytes: int = 2_000_000,
    ) -> tuple[Application, FixedModelClient]:
        client = FixedModelClient(script)
        settings = Settings(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            database_path=self.database_path,
            max_steps=max_steps,
            context_token_threshold=context_token_threshold,
            context_retain_runs=context_retain_runs,
            api_max_retries=0,
            api_retry_base_seconds=0.001,
            model_timeout_seconds=1,
            thinking_enabled=True,
            max_user_input_chars=max_user_input_chars,
            hard_context_token_limit=hard_context_token_limit,
            max_tool_calls_per_response=max_tool_calls_per_response,
            max_tool_calls_per_run=max_tool_calls_per_run,
            max_tool_arguments_chars=max_tool_arguments_chars,
            max_model_output_chars=max_model_output_chars,
            max_http_response_bytes=max_http_response_bytes,
        )
        return build_application(settings, model_client=client), client

    def app_with_real_adapter(
        self,
        *,
        api_key: str | None,
    ) -> Application:
        settings = Settings(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            database_path=self.database_path,
            api_max_retries=0,
            api_retry_base_seconds=0.001,
            model_timeout_seconds=1,
        )
        return build_application(settings)
