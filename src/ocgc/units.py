"""度量单位格式化工具（包含字节大小、Token 数量、费用与百分比）。

与数据库层无关的纯函数，单独成模块以避免 display 层转手再导出。
"""

import math


def format_bytes(n: int) -> str:
    """格式化字节大小显示。"""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def format_tokens(n: int) -> str:
    """格式化 Token 数量显示（千分位分隔）。"""
    return f"{n:,}"


def format_cost(cost: float) -> str:
    """格式化费用显示（美元单位）。"""
    if math.isclose(cost, 0.0, abs_tol=1e-9):
        return "$0.00"
    if cost < 0:
        return f"-{format_cost(abs(cost))}"
    if cost < 0.0001:
        return f"${cost:.6f}"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def format_percent(rate: float) -> str:
    """格式化百分比显示。"""
    return f"{rate * 100:.1f}%"

