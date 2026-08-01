from __future__ import annotations

from typing import Any

from ..domain.models import ToolContext, ToolResult, ToolSpec
from .base import Tool


class TodoTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="todo",
            description=(
                "管理当前 session 的待办。operation=add 新增待办，"
                "operation=list 查看当前 session 的全部未完成待办。"
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "list"],
                        "description": "待办操作",
                    },
                    "content": {
                        "type": "string",
                        "description": "add 时必填的待办内容",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                },
                "required": ["operation"],
                "additionalProperties": False,
            },
        )

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
        tool_call_id: str,
    ) -> ToolResult:
        operation = arguments["operation"]
        if context.todo_store is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.spec.name,
                ok=False,
                error_type="tool_permission_error",
                error_message="todo 工具没有获得当前 session 的存储能力",
            )
        if operation == "add":
            content = arguments.get("content")
            if not isinstance(content, str) or not content.strip():
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.spec.name,
                    ok=False,
                    error_type="missing_content",
                    error_message="todo add 必须提供非空 content",
                )
            todo, created = context.todo_store.add(
                content.strip(),
                tool_call_id,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.spec.name,
                ok=True,
                output={
                    "operation": "add",
                    "created": created,
                    "todo": {
                        "id": todo.id,
                        "content": todo.content,
                        "status": todo.status,
                    },
                },
            )

        todos = context.todo_store.list()
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.spec.name,
            ok=True,
            output={
                "operation": "list",
                "count": len(todos),
                "todos": [
                    {"id": todo.id, "content": todo.content, "status": todo.status}
                    for todo in todos
                ],
            },
        )
