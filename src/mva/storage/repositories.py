from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Iterable

from ..domain.models import Session, StoredMessage, Todo, ToolCall, TraceEvent
from ..errors import SessionNotFoundError, StorageError
from .database import Database


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _session_from_row(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        compacted_through_seq=int(row["compacted_through_seq"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status=row["status"],
    )


def _message_from_row(row: sqlite3.Row) -> StoredMessage:
    raw_calls = json.loads(row["tool_calls_json"]) if row["tool_calls_json"] else []
    calls = tuple(
        ToolCall(
            id=str(item["id"]),
            name=str(item["name"]),
            arguments=str(item["arguments"]),
        )
        for item in raw_calls
    )
    return StoredMessage(
        id=int(row["id"]),
        session_id=row["session_id"],
        run_id=row["run_id"],
        seq=int(row["seq"]),
        role=row["role"],
        content=row["content"],
        reasoning_content=row["reasoning_content"],
        tool_calls=calls,
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        created_at=row["created_at"],
    )


class SessionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, session_id: str, title: str | None = None) -> Session:
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    id, title, summary, compacted_through_seq,
                    status, created_at, updated_at
                ) VALUES (?, ?, NULL, 0, 'active', ?, ?)
                """,
                (session_id, title, now, now),
            )
        return self.get(session_id)

    def get(self, session_id: str) -> Session:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session 不存在: {session_id}")
        return _session_from_row(row)

    def exists(self, session_id: str) -> bool:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return row is not None

    def list(self) -> list[Session]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, id"
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def update_summary(
        self,
        session_id: str,
        summary: str,
        compacted_through_seq: int,
        *,
        connection: sqlite3.Connection,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE sessions
            SET summary = ?, compacted_through_seq = ?, updated_at = ?
            WHERE id = ? AND compacted_through_seq < ?
            """,
            (
                summary,
                compacted_through_seq,
                utc_now(),
                session_id,
                compacted_through_seq,
            ),
        )
        if cursor.rowcount != 1:
            raise StorageError("Context 压缩游标更新冲突")

    def touch(
        self,
        session_id: str,
        *,
        connection: sqlite3.Connection,
    ) -> None:
        cursor = connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )
        if cursor.rowcount != 1:
            raise SessionNotFoundError(f"Session 不存在: {session_id}")


class MessageRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(
        self,
        *,
        session_id: str,
        run_id: str,
        role: str,
        content: str | None,
        reasoning_content: str | None = None,
        tool_calls: Iterable[ToolCall] = (),
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        connection: sqlite3.Connection,
    ) -> StoredMessage:
        row = connection.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq "
            "FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        seq = int(row["next_seq"])
        calls_json = json.dumps(
            [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in tool_calls
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cursor = connection.execute(
            """
            INSERT INTO messages(
                session_id, run_id, seq, role, content, reasoning_content,
                tool_calls_json, tool_call_id, tool_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                run_id,
                seq,
                role,
                content,
                reasoning_content,
                calls_json,
                tool_call_id,
                tool_name,
                utc_now(),
            ),
        )
        stored = connection.execute(
            "SELECT * FROM messages WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _message_from_row(stored)

    def load_after(self, session_id: str, seq: int) -> list[StoredMessage]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*
                FROM messages AS m
                JOIN runs AS r ON r.id = m.run_id
                WHERE m.session_id = ? AND m.seq > ? AND r.context_valid = 1
                ORDER BY m.seq
                """,
                (session_id, seq),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def load_range(
        self,
        session_id: str,
        start_exclusive: int,
        end_inclusive: int,
    ) -> list[StoredMessage]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*
                FROM messages AS m
                JOIN runs AS r ON r.id = m.run_id
                WHERE m.session_id = ?
                  AND m.seq > ?
                  AND m.seq <= ?
                  AND r.context_valid = 1
                ORDER BY m.seq
                """,
                (session_id, start_exclusive, end_inclusive),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def completed_run_ranges(self, session_id: str) -> list[tuple[str, int, int]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT r.id, MIN(m.seq) AS first_seq, MAX(m.seq) AS last_seq
                FROM runs AS r
                JOIN messages AS m ON m.run_id = r.id
                WHERE r.session_id = ?
                  AND r.status != 'running'
                  AND r.context_valid = 1
                GROUP BY r.id
                ORDER BY first_seq
                """,
                (session_id,),
            ).fetchall()
        return [
            (row["id"], int(row["first_seq"]), int(row["last_seq"]))
            for row in rows
        ]


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def start_with_user_message(
        self,
        *,
        run_id: str,
        session_id: str,
        user_input: str,
        messages: MessageRepository,
        sessions: SessionRepository,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs(
                    id, session_id, status, step_count, context_valid, started_at
                ) VALUES (?, ?, 'running', 0, 1, ?)
                """,
                (run_id, session_id, utc_now()),
            )
            messages.append(
                session_id=session_id,
                run_id=run_id,
                role="user",
                content=user_input,
                connection=connection,
            )
            sessions.touch(session_id, connection=connection)

    def finish(
        self,
        *,
        run_id: str,
        status: str,
        step_count: int,
        stop_reason: str,
        error_code: str | None = None,
        context_valid: bool = True,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if status not in {"succeeded", "failed", "max_steps"}:
            raise StorageError(f"非法 run 终态: {status}")
        if connection is not None:
            self._finish(
                connection=connection,
                run_id=run_id,
                status=status,
                step_count=step_count,
                stop_reason=stop_reason,
                error_code=error_code,
                context_valid=context_valid,
            )
            return
        with self.database.transaction() as owned:
            self._finish(
                connection=owned,
                run_id=run_id,
                status=status,
                step_count=step_count,
                stop_reason=stop_reason,
                error_code=error_code,
                context_valid=context_valid,
            )

    @staticmethod
    def _finish(
        *,
        connection: sqlite3.Connection,
        run_id: str,
        status: str,
        step_count: int,
        stop_reason: str,
        error_code: str | None,
        context_valid: bool,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE runs
            SET status = ?, step_count = ?, stop_reason = ?,
                error_code = ?, context_valid = ?, finished_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (
                status,
                step_count,
                stop_reason,
                error_code,
                1 if context_valid else 0,
                utc_now(),
                run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise StorageError(f"Run 已结束或不存在: {run_id}")

    def get(self, run_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise StorageError(f"Run 不存在: {run_id}")
        return dict(row)


class TodoRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(
        self,
        session_id: str,
        content: str,
        source_tool_call_id: str,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[Todo, bool]:
        normalized = " ".join(content.casefold().split())
        existing = connection.execute(
            """
            SELECT * FROM todos
            WHERE session_id = ? AND normalized_content = ? AND status = 'open'
            """,
            (session_id, normalized),
        ).fetchone()
        if existing is not None:
            return self._from_row(existing), False

        todo_id = f"todo_{uuid.uuid4().hex[:12]}"
        now = utc_now()
        connection.execute(
            """
            INSERT INTO todos(
                id, session_id, content, normalized_content, status,
                source_tool_call_id, created_at
            ) VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                todo_id,
                session_id,
                content,
                normalized,
                source_tool_call_id,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM todos WHERE id = ? AND session_id = ?",
            (todo_id, session_id),
        ).fetchone()
        return self._from_row(row), True

    def list(
        self,
        session_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> list[Todo]:
        if connection is not None:
            rows = connection.execute(
                """
                SELECT * FROM todos
                WHERE session_id = ? AND status = 'open'
                ORDER BY created_at, id
                """,
                (session_id,),
            ).fetchall()
        else:
            with self.database.connection() as owned:
                rows = owned.execute(
                    """
                    SELECT * FROM todos
                    WHERE session_id = ? AND status = 'open'
                    ORDER BY created_at, id
                    """,
                    (session_id,),
                ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Todo:
        return Todo(
            id=row["id"],
            session_id=row["session_id"],
            content=row["content"],
            status=row["status"],
            created_at=row["created_at"],
        )


class TraceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(
        self,
        event: TraceEvent,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        values = (
            event.run_id,
            event.session_id,
            event.step,
            event.event_type,
            event.status,
            json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
            event.duration_ms,
            event.error_type,
            utc_now(),
        )
        sql = """
            INSERT INTO trace_events(
                run_id, session_id, step, event_type, status,
                payload_json, duration_ms, error_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if connection is not None:
            connection.execute(sql, values)
        else:
            with self.database.transaction() as owned:
                owned.execute(sql, values)

    def list(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            if run_id:
                rows = connection.execute(
                    """
                    SELECT * FROM trace_events
                    WHERE session_id = ? AND run_id = ?
                    ORDER BY id
                    """,
                    (session_id, run_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM trace_events
                    WHERE session_id = ?
                    ORDER BY id
                    """,
                    (session_id,),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result
