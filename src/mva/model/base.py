from __future__ import annotations

from typing import Protocol

from ..domain.models import ModelRequest, ModelResponse


class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one assistant response or raise a classified model error."""

