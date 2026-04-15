from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DailyCandle:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


def get_daily_candles(
    quote_context: Any,
    symbol: str,
    count: int = 300,
    adjust_type: str = "forward",
) -> list[DailyCandle]:
    try:
        from longbridge.openapi import AdjustType, Period
    except ImportError as exc:
        raise RuntimeError(
            "The longbridge SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    sdk_adjust_type = _resolve_adjust_type(AdjustType, adjust_type)
    candles = quote_context.candlesticks(symbol, Period.Day, count, sdk_adjust_type)
    normalized = [_normalize_candle(symbol, candle) for candle in candles]
    normalized.sort(key=lambda item: item.timestamp)
    return normalized


def _resolve_adjust_type(adjust_type_cls: Any, adjust_type: str) -> Any:
    value = adjust_type.lower().strip()
    if value in {"forward", "forward_adjust", "forwardadjust"}:
        return adjust_type_cls.ForwardAdjust
    if value in {"none", "no", "no_adjust", "noadjust"}:
        return adjust_type_cls.NoAdjust
    raise ValueError("adjust_type must be one of: forward, none")


def _normalize_candle(symbol: str, candle: Any) -> DailyCandle:
    return DailyCandle(
        symbol=symbol,
        timestamp=getattr(candle, "timestamp"),
        open=getattr(candle, "open"),
        high=getattr(candle, "high"),
        low=getattr(candle, "low"),
        close=getattr(candle, "close"),
        volume=int(getattr(candle, "volume")),
    )
