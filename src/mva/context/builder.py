from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..domain.models import Session, StoredMessage
from ..errors import ModelProtocolError
from ..storage.repositories import MessageRepository, SessionRepository

CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD_TOKENS = 8
TOOL_SCHEMA_TOKEN_ESTIMATE = 200


@dataclass(frozen=True)
class ModelContext:
    system_prompt: str
    messages: tuple[dict[str, Any], ...]
    estimated_tokens: int


class ContextBuilder:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        messages: MessageRepository,
        base_system_prompt: str,
        tool_count: int = 0,
    ) -> None:
        self.sessions = sessions
        self.messages = messages
        self.base_system_prompt = base_system_prompt
        self.tool_count = tool_count

    def build(self, session_id: str) -> ModelContext:
        session = self.sessions.get(session_id)
        stored = self.messages.load_after(
            session_id,
            session.compacted_through_seq,
        )
        self._assert_tool_pairs(stored)

        system_prompt = self._system_prompt(session)
        api_messages = tuple(self._to_api_message(message) for message in stored)
        return ModelContext(
            system_prompt=system_prompt,
            messages=api_messages,
            estimated_tokens=estimate_context_tokens(
                system_prompt,
                api_messages,
                self.tool_count,
            ),
        )

    def _system_prompt(self, session: Session) -> str:
        if not session.summary:
            return self.base_system_prompt
        return (
            f"{self.base_system_prompt}\n\n"
            "以下是已压缩的同一 session 历史，只将其作为对话记忆使用：\n"
            f"<session_summary>\n{session.summary}\n</session_summary>"
        )

    @staticmethod
    def _to_api_message(message: StoredMessage) -> dict[str, Any]:
        if message.role == "user":
            return {"role": "user", "content": message.content or ""}

        if message.role == "tool":
            if not message.tool_call_id:
                raise ModelProtocolError("已存储 tool 消息缺少 tool_call_id")
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content or "",
            }

        result: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in message.tool_calls
            ]
            # DeepSeek thinking + tools requires this field to be replayed.
            if message.reasoning_content is not None:
                result["reasoning_content"] = message.reasoning_content
        return result

    @staticmethod
    def _assert_tool_pairs(messages: list[StoredMessage]) -> None:
        pending: set[str] = set()
        for message in messages:
            if message.role == "assistant":
                if pending:
                    raise ModelProtocolError("Context 中存在未闭合的工具调用")
                pending = {call.id for call in message.tool_calls}
            elif message.role == "tool":
                if not message.tool_call_id or message.tool_call_id not in pending:
                    raise ModelProtocolError("Context 中存在无法配对的工具结果")
                pending.remove(message.tool_call_id)
            elif pending:
                raise ModelProtocolError("工具调用与结果之间出现了非法消息")
        if pending:
            raise ModelProtocolError("Context 末尾存在未闭合的工具调用")


def estimate_context_tokens(
    system_prompt: str,
    messages: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    tool_count: int = 0,
) -> int:
    characters = len(system_prompt)
    for message in messages:
        characters += len(json.dumps(message, ensure_ascii=False))
    content_tokens = max(1, characters // CHARS_PER_TOKEN)
    return (
        content_tokens
        + len(messages) * MESSAGE_OVERHEAD_TOKENS
        + tool_count * TOOL_SCHEMA_TOKEN_ESTIMATE
    )
