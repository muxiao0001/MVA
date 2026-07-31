from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ConfigurationError


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是整数") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} 必须大于 0")
    return value


def _non_negative_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是整数") from exc
    if value < 0:
        raise ConfigurationError(f"{name} 不能小于 0")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是数字") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} 必须大于 0")
    return value


def _strict_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(
        f"{name} 必须是 true/false、yes/no、on/off 或 1/0"
    )


def validate_base_url(base_url: str, allow_custom: bool) -> str:
    normalized = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("DEEPSEEK_BASE_URL 格式非法") from exc
    if parsed.scheme != "https":
        raise ConfigurationError("DEEPSEEK_BASE_URL 必须使用 HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ConfigurationError("DEEPSEEK_BASE_URL 不能包含凭据且必须有主机名")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("DEEPSEEK_BASE_URL 不能包含 query 或 fragment")
    if not allow_custom:
        if parsed.hostname.casefold() != "api.deepseek.com":
            raise ConfigurationError(
                "自定义 DeepSeek 主机默认被拒绝；确有需要时显式设置 "
                "MVA_ALLOW_CUSTOM_BASE_URL=true"
            )
        if port not in {None, 443}:
            raise ConfigurationError("DeepSeek 官方地址只允许 HTTPS 默认端口")
    return normalized


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str
    database_path: Path
    max_steps: int = 8
    context_token_threshold: int = 12_000
    context_retain_runs: int = 4
    api_max_retries: int = 2
    api_retry_base_seconds: float = 1.2
    model_timeout_seconds: float = 90.0
    thinking_enabled: bool = True
    allow_custom_base_url: bool = False
    max_user_input_chars: int = 20_000
    hard_context_token_limit: int = 64_000
    max_tool_calls_per_response: int = 4
    max_tool_calls_per_run: int = 8
    max_tool_arguments_chars: int = 16_000
    max_model_output_tokens: int = 4_096
    max_model_output_chars: int = 200_000
    max_http_response_bytes: int = 2_000_000

    def validate(self) -> None:
        validate_base_url(self.base_url, self.allow_custom_base_url)
        if not self.model.strip() or len(self.model) > 200:
            raise ConfigurationError("DEEPSEEK_MODEL 必须是 1-200 字符的非空值")
        if self.api_key is not None and not self.api_key.strip():
            raise ConfigurationError("DEEPSEEK_API_KEY 不能只包含空白")
        self._require_int_range("MVA_MAX_STEPS", self.max_steps, 1, 32)
        self._require_int_range(
            "MVA_CONTEXT_TOKEN_THRESHOLD",
            self.context_token_threshold,
            1,
            1_000_000,
        )
        self._require_int_range(
            "MVA_CONTEXT_RETAIN_RUNS",
            self.context_retain_runs,
            1,
            100,
        )
        self._require_int_range(
            "MVA_API_MAX_RETRIES",
            self.api_max_retries,
            0,
            5,
        )
        self._require_float_range(
            "MVA_API_RETRY_BASE_SECONDS",
            self.api_retry_base_seconds,
            0.001,
            60.0,
        )
        self._require_float_range(
            "MVA_MODEL_TIMEOUT_SECONDS",
            self.model_timeout_seconds,
            0.1,
            300.0,
        )
        self._require_int_range(
            "MVA_MAX_USER_INPUT_CHARS",
            self.max_user_input_chars,
            1,
            1_000_000,
        )
        self._require_int_range(
            "MVA_HARD_CONTEXT_TOKEN_LIMIT",
            self.hard_context_token_limit,
            1,
            2_000_000,
        )
        if self.context_token_threshold > self.hard_context_token_limit:
            raise ConfigurationError(
                "Context 压缩阈值不能大于 hard context limit"
            )
        self._require_int_range(
            "MVA_MAX_TOOL_CALLS_PER_RESPONSE",
            self.max_tool_calls_per_response,
            1,
            32,
        )
        self._require_int_range(
            "MVA_MAX_TOOL_CALLS_PER_RUN",
            self.max_tool_calls_per_run,
            1,
            128,
        )
        if self.max_tool_calls_per_response > self.max_tool_calls_per_run:
            raise ConfigurationError(
                "单响应工具预算不能大于单 run 工具预算"
            )
        self._require_int_range(
            "MVA_MAX_TOOL_ARGUMENTS_CHARS",
            self.max_tool_arguments_chars,
            1,
            1_000_000,
        )
        self._require_int_range(
            "MVA_MAX_MODEL_OUTPUT_TOKENS",
            self.max_model_output_tokens,
            1,
            65_536,
        )
        self._require_int_range(
            "MVA_MAX_MODEL_OUTPUT_CHARS",
            self.max_model_output_chars,
            1,
            4_000_000,
        )
        self._require_int_range(
            "MVA_MAX_HTTP_RESPONSE_BYTES",
            self.max_http_response_bytes,
            1_024,
            20_000_000,
        )

    @staticmethod
    def _require_int_range(
        name: str,
        value: int,
        minimum: int,
        maximum: int,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigurationError(f"{name} 必须是整数")
        if not minimum <= value <= maximum:
            raise ConfigurationError(
                f"{name} 必须在 {minimum} 到 {maximum} 之间"
            )

    @staticmethod
    def _require_float_range(
        name: str,
        value: float,
        minimum: float,
        maximum: float,
    ) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ConfigurationError(f"{name} 必须是有限数字")
        if not minimum <= float(value) <= maximum:
            raise ConfigurationError(
                f"{name} 必须在 {minimum} 到 {maximum} 之间"
            )

    @classmethod
    def from_env(cls) -> "Settings":
        database_path = Path(os.getenv("MVA_DB_PATH", "var/agent.db")).expanduser()
        settings = cls(
            api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            database_path=database_path,
            max_steps=_positive_int("MVA_MAX_STEPS", 8),
            context_token_threshold=_positive_int("MVA_CONTEXT_TOKEN_THRESHOLD", 12_000),
            context_retain_runs=_positive_int("MVA_CONTEXT_RETAIN_RUNS", 4),
            api_max_retries=_non_negative_int("MVA_API_MAX_RETRIES", 2),
            api_retry_base_seconds=_positive_float("MVA_API_RETRY_BASE_SECONDS", 1.2),
            model_timeout_seconds=_positive_float("MVA_MODEL_TIMEOUT_SECONDS", 90.0),
            thinking_enabled=_strict_bool("MVA_THINKING_ENABLED", True),
            allow_custom_base_url=_strict_bool(
                "MVA_ALLOW_CUSTOM_BASE_URL",
                False,
            ),
            max_user_input_chars=_positive_int(
                "MVA_MAX_USER_INPUT_CHARS",
                20_000,
            ),
            hard_context_token_limit=_positive_int(
                "MVA_HARD_CONTEXT_TOKEN_LIMIT",
                64_000,
            ),
            max_tool_calls_per_response=_positive_int(
                "MVA_MAX_TOOL_CALLS_PER_RESPONSE",
                4,
            ),
            max_tool_calls_per_run=_positive_int(
                "MVA_MAX_TOOL_CALLS_PER_RUN",
                8,
            ),
            max_tool_arguments_chars=_positive_int(
                "MVA_MAX_TOOL_ARGUMENTS_CHARS",
                16_000,
            ),
            max_model_output_tokens=_positive_int(
                "MVA_MAX_MODEL_OUTPUT_TOKENS",
                4_096,
            ),
            max_model_output_chars=_positive_int(
                "MVA_MAX_MODEL_OUTPUT_CHARS",
                200_000,
            ),
            max_http_response_bytes=_positive_int(
                "MVA_MAX_HTTP_RESPONSE_BYTES",
                2_000_000,
            ),
        )
        settings.validate()
        return settings


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_prompt(filename: str) -> str:
    path = project_root() / "prompts" / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigurationError(f"无法读取 prompt: {path}") from exc
