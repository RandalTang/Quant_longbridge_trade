from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from .account import AccountService
from .historical_data import get_daily_candles
from .strategies import EmaCrossSignal, evaluate_ema_cross, format_signal_message
from .monitor import normalize_quote


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


def check_ema_preview_signal(
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
    latest_quote = normalize_quote(quote_context.quote([symbol])[0])

    quote_trade_date = _quote_trade_date(latest_quote.timestamp)
    if candles and candles[-1].timestamp.date().isoformat() == quote_trade_date:
        candles[-1] = replace(candles[-1], close=latest_quote.last_done)
    else:
        candles.append(
            replace(
                candles[-1],
                timestamp=_quote_timestamp(latest_quote.timestamp, candles[-1].timestamp),
                open=latest_quote.last_done,
                high=latest_quote.last_done,
                low=latest_quote.last_done,
                close=latest_quote.last_done,
                volume=0,
            )
        )

    signal = evaluate_ema_cross(candles, symbol=symbol, fast=fast, slow=slow, mode="PREVIEW")
    current_position = _current_position_text(trade_context, symbol) if trade_context else None
    message = format_signal_message(signal, current_position=current_position)
    return SignalCheckResult(signal=signal, message=message, current_position=current_position)


def check_sqqq_death_cross(
    quote_context,
    symbol: str = "SQQQ.US",
    fast: int = 5,
    slow: int = 30,
    candle_count: int = 300,
    adjust_type: str = "forward",
    trade_context=None,
    preview: bool = False,
) -> SignalCheckResult:
    checker = check_ema_preview_signal if preview else check_ema_signal
    result = checker(
        quote_context=quote_context,
        trade_context=trade_context,
        symbol=symbol,
        fast=fast,
        slow=slow,
        candle_count=candle_count,
        adjust_type=adjust_type,
    )
    if result.signal.signal not in {"SELL", "SELL_PREVIEW"}:
        return result

    status = _ema_position_text(result.signal)
    prefix = "SQQQ EMA 死叉预警" if preview else "SQQQ EMA 死叉确认"
    message = "\n".join(
        [
            prefix,
            "",
            f"标的：{result.signal.symbol}",
            f"日期：{result.signal.trade_date}",
            f"信号：{result.signal.signal}",
            f"原因：{result.signal.reason}",
            "",
            f"{'预估收盘价' if preview else '收盘价'}：{result.signal.close:.4f}",
            f"EMA 快线：{result.signal.fast_ema:.4f}",
            f"EMA 慢线：{result.signal.slow_ema:.4f}",
            f"昨日快线：{result.signal.previous_fast_ema:.4f}",
            f"昨日慢线：{result.signal.previous_slow_ema:.4f}",
            f"当前状态：{status}",
            "",
            f"当前持仓：{result.current_position}" if result.current_position is not None else "",
            "",
            "建议动作：如果当前持有 SQQQ，考虑先卖出空仓；等待 TQQQ 金叉再切回 TQQQ。",
        ]
    ).strip()
    return SignalCheckResult(signal=result.signal, message=message, current_position=result.current_position)


def format_secondary_signal_status(result: SignalCheckResult, title: str) -> str:
    signal = result.signal
    return "\n".join(
        [
            title,
            "",
            f"标的：{signal.symbol}",
            f"日期：{signal.trade_date}",
            f"信号：{signal.signal}",
            f"原因：{signal.reason}",
            "",
            f"{'预估收盘价' if signal.mode == 'PREVIEW' else '收盘价'}：{signal.close:.4f}",
            f"EMA 快线：{signal.fast_ema:.4f}",
            f"EMA 慢线：{signal.slow_ema:.4f}",
            f"昨日快线：{signal.previous_fast_ema:.4f}",
            f"昨日慢线：{signal.previous_slow_ema:.4f}",
            "",
            f"当前持仓：{result.current_position}" if result.current_position is not None else "",
            "",
            f"当前状态：{_ema_position_text(signal)}",
            "",
            "策略含义：SQQQ 死叉时，考虑从 SQQQ 退出到空仓；等待 TQQQ 金叉再切回 TQQQ。",
        ]
    ).strip()


def _ema_position_text(signal: EmaCrossSignal) -> str:
    if signal.fast_ema > signal.slow_ema:
        return "EMA 快线在慢线上方，偏多状态"
    if signal.fast_ema < signal.slow_ema:
        return "EMA 快线在慢线下方，偏空状态"
    return "EMA 快线与慢线基本相等，临界状态"


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


def _quote_trade_date(timestamp: Optional[str]) -> Optional[str]:
    if not timestamp:
        return None
    return str(timestamp).split(" ", 1)[0].split("T", 1)[0]


def _quote_timestamp(timestamp: Optional[str], fallback: datetime) -> datetime:
    if not timestamp:
        return fallback
    value = str(timestamp).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback
