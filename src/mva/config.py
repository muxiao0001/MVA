from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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

    @classmethod
    def from_env(cls) -> "Settings":
        database_path = Path(os.getenv("MVA_DB_PATH", "var/agent.db")).expanduser()
        return cls(
            api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            database_path=database_path,
            max_steps=_positive_int("MVA_MAX_STEPS", 8),
            context_token_threshold=_positive_int("MVA_CONTEXT_TOKEN_THRESHOLD", 12_000),
            context_retain_runs=_positive_int("MVA_CONTEXT_RETAIN_RUNS", 4),
            api_max_retries=_non_negative_int("MVA_API_MAX_RETRIES", 2),
            api_retry_base_seconds=_positive_float("MVA_API_RETRY_BASE_SECONDS", 1.2),
            model_timeout_seconds=_positive_float("MVA_MODEL_TIMEOUT_SECONDS", 90.0),
            thinking_enabled=os.getenv("MVA_THINKING_ENABLED", "true").lower()
            not in {"0", "false", "no"},
        )


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_prompt(filename: str) -> str:
    path = project_root() / "prompts" / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigurationError(f"无法读取 prompt: {path}") from exc

