from __future__ import annotations

from typing import Any

from ..domain.models import ToolContext, ToolResult, ToolSpec
from .base import Tool

_MOCK_INDEX = (
    {
        "title": "DeepSeek Tool Calls 指南（Mock）",
        "snippet": "DeepSeek 的 OpenAI 兼容接口可返回原生 tool_calls。",
        "url": "mock://deepseek/tool-calls",
        "keywords": ("deepseek", "工具", "tool", "agent"),
    },
    {
        "title": "Python ast 安全计算（Mock）",
        "snippet": "限制 AST 节点白名单可避免 calculator 执行任意代码。",
        "url": "mock://python/safe-calculator",
        "keywords": ("python", "ast", "计算", "安全"),
    },
    {
        "title": "SQLite Session 持久化（Mock）",
        "snippet": "使用 session_id 约束消息和业务数据可实现会话隔离。",
        "url": "mock://sqlite/session-storage",
        "keywords": ("sqlite", "session", "会话", "持久化"),
    },
    {
        "title": "Agent Context 压缩（Mock）",
        "snippet": "滚动摘要配合最近完整交互，可降低长对话上下文体积。",
        "url": "mock://agent/context-compaction",
        "keywords": ("agent", "context", "上下文", "压缩", "摘要"),
    },
)


class MockSearchTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search",
            description=(
                "查询本地固定的模拟搜索索引。结果不是实时联网信息，"
                "回答用户时必须明确说明是 Mock 数据。"
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                        "minLength": 1,
                        "maxLength": 120,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回几条结果",
                        "minimum": 1,
                        "maximum": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
        tool_call_id: str,
    ) -> ToolResult:
        del context
        query = " ".join(arguments["query"].casefold().split())
        limit = int(arguments.get("limit", 3))
        terms = tuple(term for term in query.replace("-", " ").split() if term)

        scored: list[tuple[int, dict[str, Any]]] = []
        for item in _MOCK_INDEX:
            haystack = " ".join(
                (
                    item["title"],
                    item["snippet"],
                    *item["keywords"],
                )
            ).casefold()
            score = sum(2 if term in item["keywords"] else 1 for term in terms if term in haystack)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["title"]))

        results = [
            {
                "title": item["title"],
                "snippet": item["snippet"],
                "url": item["url"],
            }
            for _, item in scored[:limit]
        ]
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.spec.name,
            ok=True,
            output={
                "source": "mock",
                "notice": "以下是本地固定 Mock 数据，不是实时联网搜索结果。",
                "query": arguments["query"],
                "results": results,
            },
        )

