from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


class Redactor:
    SENSITIVE_EXACT_KEYS = {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "bearer_token",
    }
    SENSITIVE_FRAGMENTS = (
        "api_key",
        "authorization",
        "password",
        "secret",
        "reasoning_content",
    )

    def sanitize(self, value: Any) -> Any:
        if is_dataclass(value):
            value = asdict(value)
        if isinstance(value, dict):
            clean: dict[str, Any] = {}
            for key, child in value.items():
                normalized = str(key).casefold()
                if (
                    normalized in self.SENSITIVE_EXACT_KEYS
                    or normalized.endswith("_token")
                    or any(
                        fragment in normalized
                        for fragment in self.SENSITIVE_FRAGMENTS
                    )
                ):
                    clean[str(key)] = "[REDACTED]"
                else:
                    clean[str(key)] = self.sanitize(child)
            return clean
        if isinstance(value, (list, tuple, set)):
            return [self.sanitize(item) for item in value]
        if isinstance(value, bytes):
            return f"<{len(value)} bytes>"
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("{", "[")):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    return value
                return self.sanitize(parsed)
            return value
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return repr(value)
