from __future__ import annotations

import sqlite3
from typing import Any

from ..domain.models import TraceEvent
from ..storage.repositories import TraceRepository
from .redaction import Redactor


class TraceRecorder:
    def __init__(
        self,
        repository: TraceRepository,
        redactor: Redactor | None = None,
    ) -> None:
        self.repository = repository
        self.redactor = redactor or Redactor()

    def emit(
        self,
        *,
        run_id: str,
        session_id: str,
        step: int,
        event_type: str,
        status: str,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        error_type: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        sanitized = self.redactor.sanitize(payload or {})
        self.repository.append(
            TraceEvent(
                run_id=run_id,
                session_id=session_id,
                step=step,
                event_type=event_type,
                status=status,
                payload=sanitized,
                duration_ms=duration_ms,
                error_type=error_type,
            ),
            connection=connection,
        )

    def list(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.list(session_id=session_id, run_id=run_id)
