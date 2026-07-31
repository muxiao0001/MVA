from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable

from ..domain.models import ToolContext, ToolResult, ToolSpec
from .base import Tool

BinaryOperator = Callable[[float | int, float | int], float | int]


class CalculatorTool(Tool):
    _BINARY_OPERATORS: dict[type[ast.operator], BinaryOperator] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _UNARY_OPERATORS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description=(
                "安全计算算术表达式。支持 +、-、*、/、//、%、** 和括号；"
                "不得用于日期、单位换算或执行代码。"
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "需要计算的纯算术表达式",
                        "minLength": 1,
                        "maxLength": 200,
                    }
                },
                "required": ["expression"],
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
        expression = arguments["expression"]
        try:
            tree = ast.parse(expression, mode="eval")
            value = self._evaluate(tree.body)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("结果不是有限数字")
        except (SyntaxError, ArithmeticError, ValueError, TypeError) as exc:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.spec.name,
                ok=False,
                error_type="invalid_expression",
                error_message=f"无法计算该表达式: {exc}",
            )
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.spec.name,
            ok=True,
            output={"expression": expression, "value": value},
        )

    def _evaluate(self, node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("只允许数字常量")
            if abs(node.value) > 1e100:
                raise ValueError("数字过大")
            return node.value

        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UNARY_OPERATORS:
            result = self._UNARY_OPERATORS[type(node.op)](self._evaluate(node.operand))
            return self._bounded(result)

        if isinstance(node, ast.BinOp) and type(node.op) in self._BINARY_OPERATORS:
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("指数绝对值不能超过 100")
            result = self._BINARY_OPERATORS[type(node.op)](left, right)
            return self._bounded(result)

        raise ValueError(f"不允许的语法: {type(node).__name__}")

    @staticmethod
    def _bounded(value: float | int) -> float | int:
        if isinstance(value, complex) or abs(value) > 1e100:
            raise ValueError("结果过大")
        return value

