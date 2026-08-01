from __future__ import annotations


def direct_answer(step: int) -> str:
    return f"第 {step} 步：模型已直接回答，run 结束。"


def tool_calls(step: int, names: list[str]) -> str:
    return f"第 {step} 步：模型请求调用工具：{', '.join(names)}。"


def tool_result(name: str, ok: bool) -> str:
    state = "成功" if ok else "失败"
    return f"工具 {name} 执行{state}，继续交由模型处理。"


def max_steps(limit: int) -> str:
    return f"达到模型轮次上限（{limit}），run 已停止。"


def failure(code: str) -> str:
    return f"run 因 {code} 终止；session 仍可继续使用。"

