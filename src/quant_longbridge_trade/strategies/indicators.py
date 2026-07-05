"""公共技术指标计算。所有策略共用，纯函数，只依赖 Decimal。"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional


def ema(values: list[Decimal], span: int) -> list[Decimal]:
    """指数移动平均，逐根递推，返回和输入等长的序列。"""
    alpha = Decimal("2") / Decimal(span + 1)
    result: list[Decimal] = []
    current: Optional[Decimal] = None
    for value in values:
        current = value if current is None else value * alpha + current * (Decimal("1") - alpha)
        result.append(current)
    return result
