from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..domain.models import ToolCall, ToolContext, ToolResult
from ..errors import StorageError, ToolRegistrationError, ToolValidationError
from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if not name or not name.replace("_", "").isalnum() or name.lower() != name:
            raise ToolRegistrationError(f"非法工具名: {name!r}")
        if name in self._tools:
            raise ToolRegistrationError(f"工具名重复: {name}")
        self._tools[name] = tool

    def specs(self) -> tuple[dict[str, Any], ...]:
        return tuple(tool.spec.as_api_tool() for tool in self._tools.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def invoke(self, call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type="unknown_tool",
                error_message=f"未注册工具: {call.name}",
            )

        try:
            arguments = json.loads(
                call.arguments,
                parse_constant=self._reject_non_standard_constant,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            detail = getattr(exc, "msg", type(exc).__name__)
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type="invalid_json",
                error_message=f"工具参数不是合法 JSON: {detail}",
            )
        if self._exceeds_json_depth(arguments):
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type="invalid_json",
                error_message="工具参数 JSON 嵌套层级超过 64",
            )
        if not isinstance(arguments, dict):
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type="invalid_arguments",
                error_message="工具参数必须是 JSON object",
            )

        try:
            validate_schema(arguments, tool.spec.parameters_schema)
        except ToolValidationError as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type=exc.code,
                error_message=exc.message,
            )

        try:
            result = tool.execute(arguments, context, call.id)
        except (sqlite3.Error, StorageError):
            raise
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type="tool_execution_error",
                error_message=f"工具执行异常: {type(exc).__name__}",
            )
        if result.tool_call_id != call.id or result.tool_name != call.name:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_type="invalid_tool_result",
                error_message="工具返回的调用标识不匹配",
            )
        return result

    @staticmethod
    def _reject_non_standard_constant(value: str) -> None:
        raise ValueError(f"不允许非标准 JSON 常量: {value}")

    @staticmethod
    def _exceeds_json_depth(value: Any, maximum: int = 64) -> bool:
        stack: list[tuple[Any, int]] = [(value, 1)]
        while stack:
            item, depth = stack.pop()
            if depth > maximum:
                return True
            if isinstance(item, dict):
                stack.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item)
        return False


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the small JSON Schema subset used by this project."""

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(item) for item in schema["enum"])
        raise ToolValidationError(f"{path} 必须是以下值之一: {allowed}")

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise ToolValidationError(f"{path} 必须是 object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                raise ToolValidationError(f"{path}.{name} 是必填参数")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ToolValidationError(f"{path} 包含未知参数: {names}")
        for name, item in value.items():
            child_schema = properties.get(name)
            if child_schema is not None:
                validate_schema(item, child_schema, f"{path}.{name}")
        return

    if expected == "array":
        if not isinstance(value, list):
            raise ToolValidationError(f"{path} 必须是 array")
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise ToolValidationError(f"{path} 项目数量不足")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ToolValidationError(f"{path} 项目数量过多")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema(item, item_schema, f"{path}[{index}]")
        return

    if expected == "string":
        if not isinstance(value, str):
            raise ToolValidationError(f"{path} 必须是 string")
        if len(value) < int(schema.get("minLength", 0)):
            raise ToolValidationError(f"{path} 太短")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ToolValidationError(f"{path} 太长")
        return

    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError(f"{path} 必须是 integer")
        _validate_number_range(value, schema, path)
        return

    if expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolValidationError(f"{path} 必须是 number")
        _validate_number_range(value, schema, path)
        return

    if expected == "boolean" and not isinstance(value, bool):
        raise ToolValidationError(f"{path} 必须是 boolean")


def _validate_number_range(
    value: int | float,
    schema: dict[str, Any],
    path: str,
) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        raise ToolValidationError(f"{path} 小于允许的最小值")
    if "maximum" in schema and value > schema["maximum"]:
        raise ToolValidationError(f"{path} 大于允许的最大值")
