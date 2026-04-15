from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .account import AccountService
from .historical_data import get_daily_candles
from .strategies import EmaCrossSignal, evaluate_ema_cross, format_signal_message


@dataclass(frozen=True)
class SignalCheckResult:
    signal: EmaCrossSignal
    message: str
    current_position: Optional[str]


def check_ema_signal(
    quote_context,
    symbol: str = "TQQQ.US",
    fast: int = 5,
    slow: int = 30,
    candle_count: int = 300,
    adjust_type: str = "forward",
    trade_context=None,
) -> SignalCheckResult:
    candles = get_daily_candles(
        quote_context=quote_context,
        symbol=symbol,
        count=candle_count,
        adjust_type=adjust_type,
    )
    signal = evaluate_ema_cross(candles, symbol=symbol, fast=fast, slow=slow)
    current_position = _current_position_text(trade_context, symbol) if trade_context else None
    message = format_signal_message(signal, current_position=current_position)
    return SignalCheckResult(signal=signal, message=message, current_position=current_position)


def _current_position_text(trade_context, symbol: str) -> str:
    try:
        positions = AccountService(trade_context).get_stock_positions(symbols=[symbol])
    except Exception as exc:
        return f"查询失败：{exc}"
    if not positions:
        return "0"
    return ", ".join(
        f"{item.get('quantity') or '0'} 股，可用 {item.get('available_quantity') or '0'}"
        for item in positions
    )
