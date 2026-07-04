from __future__ import annotations

import os
from typing import Optional

from ..config import load_local_env
from .base import AccountSnapshot, Broker, DailyCandle, QuoteSnapshot

SUPPORTED_BROKERS = ("longbridge",)


def resolve_broker_name(name: Optional[str] = None) -> str:
    """解析券商名。优先级：显式传入 name > 环境变量 BROKER > 默认 longbridge。"""
    load_local_env()
    return (name or os.getenv("BROKER") or "longbridge").strip().lower()


def create_broker(name: Optional[str] = None) -> Broker:
    """根据名字创建券商实例。以后接 IBKR / 嘉信时，在这里加分支即可。"""
    resolved = resolve_broker_name(name)

    if resolved in {"longbridge", "lb"}:
        from .longbridge import LongbridgeBroker

        return LongbridgeBroker()

    raise ValueError(
        f"Unsupported broker: {resolved!r}. Supported: {', '.join(SUPPORTED_BROKERS)}"
    )


__all__ = [
    "AccountSnapshot",
    "Broker",
    "DailyCandle",
    "QuoteSnapshot",
    "SUPPORTED_BROKERS",
    "create_broker",
    "resolve_broker_name",
]
