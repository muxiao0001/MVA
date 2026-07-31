from __future__ import annotations

import uuid

from ..domain.models import Session
from ..storage.repositories import SessionRepository


class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository

    def create(self, title: str | None = None) -> Session:
        normalized_title = title.strip() if title and title.strip() else None
        session_id = f"s_{uuid.uuid4().hex[:12]}"
        return self.repository.create(session_id, normalized_title)

    def list(self) -> list[Session]:
        return self.repository.list()

    def get(self, session_id: str) -> Session:
        return self.repository.get(session_id)

    def resume(self, session_id: str) -> Session:
        return self.get(session_id)

