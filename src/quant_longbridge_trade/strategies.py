from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .historical_data import DailyCandle


@dataclass(frozen=True)
class EmaCrossSignal:
    symbol: str
    signal: str
    trade_date: str
    close: Decimal
    fast_ema: Decimal
    slow_ema: Decimal
    previous_fast_ema: Decimal
    previous_slow_ema: Decimal
    reason: str
    mode: str = "CONFIRMED"

    @property
    def has_signal(self) -> bool:
        return self.signal in {"BUY", "SELL", "BUY_PREVIEW", "SELL_PREVIEW"}

    @property
    def dedupe_key(self) -> str:
        return f"{self.symbol}:{self.trade_date}:EMA:{self.mode}:{self.signal}"


def evaluate_ema_cross(
    candles: list[DailyCandle],
    symbol: str,
    fast: int = 5,
    slow: int = 30,
    mode: str = "CONFIRMED",
) -> EmaCrossSignal:
    if fast <= 0 or slow <= 0:
        raise ValueError("fast and slow must be positive integers")
    if fast >= slow:
        raise ValueError("fast must be smaller than slow")
    if len(candles) < slow + 2:
        raise ValueError(f"Need at least {slow + 2} candles, got {len(candles)}")

    closes = [candle.close for candle in candles]
    fast_values = _ema(closes, fast)
    slow_values = _ema(closes, slow)

    prev_fast = fast_values[-2]
    prev_slow = slow_values[-2]
    latest_fast = fast_values[-1]
    latest_slow = slow_values[-1]
    latest = candles[-1]

    if prev_fast <= prev_slow and latest_fast > latest_slow:
        signal = "BUY_PREVIEW" if mode == "PREVIEW" else "BUY"
        reason = f"EMA{fast} 上穿 EMA{slow}"
    elif prev_fast >= prev_slow and latest_fast < latest_slow:
        signal = "SELL_PREVIEW" if mode == "PREVIEW" else "SELL"
        reason = f"EMA{fast} 下穿 EMA{slow}"
    else:
        signal = "NO_PREVIEW_SIGNAL" if mode == "PREVIEW" else "NO_SIGNAL"
        reason = f"EMA{fast}/EMA{slow} 未发生穿越"

    return EmaCrossSignal(
        symbol=symbol,
        signal=signal,
        trade_date=latest.timestamp.date().isoformat(),
        close=latest.close,
        fast_ema=latest_fast,
        slow_ema=latest_slow,
        previous_fast_ema=prev_fast,
        previous_slow_ema=prev_slow,
        reason=reason,
        mode=mode,
    )


def format_signal_message(
    signal: EmaCrossSignal,
    current_position: Optional[str] = None,
) -> str:
    lines = [
        "TQQQ EMA 策略预警" if signal.mode == "PREVIEW" else "TQQQ EMA 策略确认",
        "",
        f"标的：{signal.symbol}",
        f"日期：{signal.trade_date}",
        f"信号：{signal.signal}",
        f"原因：{signal.reason}",
        "",
        f"{'预估收盘价' if signal.mode == 'PREVIEW' else '收盘价'}：{_fmt_decimal(signal.close)}",
        f"EMA 快线：{_fmt_decimal(signal.fast_ema)}",
        f"EMA 慢线：{_fmt_decimal(signal.slow_ema)}",
        f"昨日快线：{_fmt_decimal(signal.previous_fast_ema)}",
        f"昨日慢线：{_fmt_decimal(signal.previous_slow_ema)}",
    ]
    if current_position is not None:
        lines.extend(["", f"当前持仓：{current_position}"])
    if signal.mode == "PREVIEW":
        lines.extend(["", "说明：这是收盘前预警，不是确认信号；最后几分钟可能变化。"])
    if signal.signal in {"BUY", "BUY_PREVIEW"}:
        lines.extend(["", "建议动作：关注收盘确认，检查账户后考虑买入。"])
    elif signal.signal in {"SELL", "SELL_PREVIEW"}:
        lines.extend(["", "建议动作：关注收盘确认，检查账户后考虑卖出。"])
    else:
        lines.extend(["", "建议动作：无。"])
    return "\n".join(lines)


def _ema(values: list[Decimal], span: int) -> list[Decimal]:
    alpha = Decimal("2") / Decimal(span + 1)
    result: list[Decimal] = []
    current: Optional[Decimal] = None
    for value in values:
        current = value if current is None else value * alpha + current * (Decimal("1") - alpha)
        result.append(current)
    return result


def _fmt_decimal(value: Decimal) -> str:
    return f"{value:.4f}"
