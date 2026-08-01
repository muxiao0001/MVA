from __future__ import annotations

import uuid

from ..domain.models import Session
from ..errors import InputValidationError
from ..storage.repositories import SessionRepository

MAX_SESSION_TITLE_CHARS = 200


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)


class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository

    def create(self, title: str | None = None) -> Session:
        if title is not None and not isinstance(title, str):
            raise InputValidationError("Session 标题必须是文本")
        if title is not None and len(title) > MAX_SESSION_TITLE_CHARS:
            raise InputValidationError(
                f"Session 标题超过 {MAX_SESSION_TITLE_CHARS} 字符上限"
            )
        if title is not None and _has_control_characters(title):
            raise InputValidationError("Session 标题不能包含控制字符")
        normalized_title = title.strip() if title and title.strip() else None
        session_id = f"s_{uuid.uuid4().hex[:12]}"
        return self.repository.create(session_id, normalized_title)

    def list(self) -> list[Session]:
        return self.repository.list()

    def get(self, session_id: str) -> Session:
        return self.repository.get(session_id)

    def resume(self, session_id: str) -> Session:
        return self.get(session_id)
