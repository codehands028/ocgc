"""字节大小格式化工具。

与数据库层无关的纯函数，单独成模块以避免 display 层转手再导出。
"""


def format_bytes(n: int) -> str:
    """格式化字节大小显示。"""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"
