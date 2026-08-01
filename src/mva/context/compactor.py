from __future__ import annotations

import json

from ..domain.models import CompactionResult, StoredMessage
from ..storage.database import Database
from ..storage.repositories import MessageRepository, SessionRepository
from .builder import ContextBuilder, estimate_context_tokens


class ContextCompactor:
    """Deterministic rolling summary over completed, closed runs."""

    def __init__(
        self,
        *,
        database: Database,
        sessions: SessionRepository,
        messages: MessageRepository,
        context_builder: ContextBuilder,
        token_threshold: int,
        retain_recent_runs: int,
        summary_max_chars: int = 6_000,
    ) -> None:
        self.database = database
        self.sessions = sessions
        self.messages = messages
        self.context_builder = context_builder
        self.token_threshold = token_threshold
        self.retain_recent_runs = retain_recent_runs
        self.summary_max_chars = summary_max_chars

    def compact_if_needed(self, session_id: str) -> CompactionResult:
        before = self.context_builder.build(session_id)
        if before.estimated_tokens <= self.token_threshold:
            session = self.sessions.get(session_id)
            return CompactionResult(
                compacted=False,
                before_tokens=before.estimated_tokens,
                after_tokens=before.estimated_tokens,
                compacted_through_seq=session.compacted_through_seq,
            )

        session = self.sessions.get(session_id)
        run_ranges = [
            item
            for item in self.messages.completed_run_ranges(session_id)
            if item[2] > session.compacted_through_seq
        ]
        if len(run_ranges) <= self.retain_recent_runs:
            return CompactionResult(
                compacted=False,
                before_tokens=before.estimated_tokens,
                after_tokens=before.estimated_tokens,
                compacted_through_seq=session.compacted_through_seq,
                reason="insufficient_closed_history",
            )

        compactable = run_ranges[: -self.retain_recent_runs]
        boundary = compactable[-1][2]
        older = self.messages.load_range(
            session_id,
            session.compacted_through_seq,
            boundary,
        )
        summary = self._rolling_summary(session.summary, older)
        if not summary:
            return CompactionResult(
                compacted=False,
                before_tokens=before.estimated_tokens,
                after_tokens=before.estimated_tokens,
                compacted_through_seq=session.compacted_through_seq,
                reason="empty_summary",
            )

        with self.database.transaction() as connection:
            self.sessions.update_summary(
                session_id,
                summary,
                boundary,
                connection=connection,
            )

        after = self.context_builder.build(session_id)
        return CompactionResult(
            compacted=True,
            before_tokens=before.estimated_tokens,
            after_tokens=after.estimated_tokens,
            compacted_through_seq=boundary,
            reason="token_threshold",
        )

    def _rolling_summary(
        self,
        previous_summary: str | None,
        messages: list[StoredMessage],
    ) -> str:
        sections: list[str] = []
        if previous_summary:
            sections.append("[更早历史摘要]\n" + previous_summary)
        if messages:
            sections.append(
                "[本次新增摘要]\n"
                + "\n".join(self._summarize_message(message) for message in messages)
            )
        merged = "\n".join(section for section in sections if section.strip()).strip()
        if len(merged) <= self.summary_max_chars:
            return merged

        head_size = self.summary_max_chars * 2 // 5
        tail_size = self.summary_max_chars - head_size - 40
        return (
            merged[:head_size]
            + "\n...[中间冗余历史已压缩]...\n"
            + merged[-tail_size:]
        )

    @staticmethod
    def _summarize_message(message: StoredMessage) -> str:
        content = (message.content or "").strip().replace("\x00", "")
        content = content[:1_000]
        if message.role == "user":
            return f"- 用户：{content}"
        if message.role == "tool":
            return f"- 工具结果（{message.tool_name or 'unknown'}）：{content}"

        tool_note = ""
        if message.tool_calls:
            calls = [
                {
                    "name": call.name,
                    "arguments": call.arguments[:500],
                }
                for call in message.tool_calls
            ]
            tool_note = "；工具调用：" + json.dumps(calls, ensure_ascii=False)
        return f"- Agent：{content}{tool_note}"

