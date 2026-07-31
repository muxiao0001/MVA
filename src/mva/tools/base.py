from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..domain.models import ToolContext, ToolResult, ToolSpec


class Tool(ABC):
    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
        tool_call_id: str,
    ) -> ToolResult:
        raise NotImplementedError

