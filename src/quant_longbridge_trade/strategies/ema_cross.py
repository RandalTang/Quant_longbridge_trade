"""EMA 快慢线金叉/死叉策略（默认 EMA5/EMA30，用于 TQQQ/SQQQ 轮动）。

纯函数：输入日线 K 线列表，输出带 dedupe_key 的信号 dataclass，
不碰网络、SDK 和券商。新策略照这个模式写。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..brokers.base import DailyCandle
from .indicators import ema

# 信号词统一在这里定义；改文案只改这里，其他代码都引用常量
SIGNAL_BUY = "快买买"
SIGNAL_BUY_PREVIEW = "买买买买"
SIGNAL_SELL = "卖出吧"
SIGNAL_SELL_PREVIEW = "卖卖卖卖"
SIGNAL_NONE = "不用管！"
SIGNAL_NONE_PREVIEW = "不用管"

ACTION_SIGNALS = {SIGNAL_BUY, SIGNAL_BUY_PREVIEW, SIGNAL_SELL, SIGNAL_SELL_PREVIEW}
SELL_SIGNALS = {SIGNAL_SELL, SIGNAL_SELL_PREVIEW}
BUY_SIGNALS = {SIGNAL_BUY, SIGNAL_BUY_PREVIEW}


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
    fast_slow_diff: Decimal
    previous_fast_slow_diff: Decimal
    higher_line: str
    reason: str
    mode: str = "CONFIRMED"

    @property
    def has_signal(self) -> bool:
        return self.signal in ACTION_SIGNALS

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
    fast_values = ema(closes, fast)
    slow_values = ema(closes, slow)

    prev_fast = fast_values[-2]
    prev_slow = slow_values[-2]
    latest_fast = fast_values[-1]
    latest_slow = slow_values[-1]
    latest = candles[-1]

    prev_diff = prev_fast - prev_slow
    latest_diff = latest_fast - latest_slow
    if latest_diff > 0:
        higher_line = f"EMA{fast}"
    elif latest_diff < 0:
        higher_line = f"EMA{slow}"
    else:
        higher_line = "相等"

    if prev_fast <= prev_slow and latest_fast > latest_slow:
        signal = SIGNAL_BUY_PREVIEW if mode == "PREVIEW" else SIGNAL_BUY
        reason = f"EMA{fast} 上穿 EMA{slow}"
    elif prev_fast >= prev_slow and latest_fast < latest_slow:
        signal = SIGNAL_SELL_PREVIEW if mode == "PREVIEW" else SIGNAL_SELL
        reason = f"EMA{fast} 下穿 EMA{slow}"
    else:
        signal = SIGNAL_NONE_PREVIEW if mode == "PREVIEW" else SIGNAL_NONE
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
        fast_slow_diff=latest_diff,
        previous_fast_slow_diff=prev_diff,
        higher_line=higher_line,
        reason=reason,
        mode=mode,
    )


def format_signal_message(
    signal: EmaCrossSignal,
    current_position: Optional[str] = None,
) -> str:
    lines = [
        f"信号：{signal.signal}",
        "TQQQ EMA 策略预警" if signal.mode == "PREVIEW" else "TQQQ EMA 策略确认",
        "",
        f"标的：{signal.symbol}",
        f"日期：{signal.trade_date}",
        f"信号：{signal.signal}",
        f"原因：{signal.reason}",
        "",
        f"EMA 快线：{_fmt_decimal(signal.fast_ema)}",
        f"EMA 慢线：{_fmt_decimal(signal.slow_ema)}",
        f"昨日快线：{_fmt_decimal(signal.previous_fast_ema)}",
        f"昨日慢线：{_fmt_decimal(signal.previous_slow_ema)}",
        f"今日快慢差：{_fmt_signed(signal.fast_slow_diff)}",
        f"昨日快慢差：{_fmt_signed(signal.previous_fast_slow_diff)}",
        f"当前在上方：{signal.higher_line}",
    ]
    if current_position is not None:
        lines.extend(["", f"当前持仓：{current_position}"])
    return "\n".join(lines)


def ema_position_text(signal: EmaCrossSignal) -> str:
    if signal.fast_ema > signal.slow_ema:
        return "EMA 快线在慢线上方，偏多状态"
    if signal.fast_ema < signal.slow_ema:
        return "EMA 快线在慢线下方，偏空状态"
    return "EMA 快线与慢线基本相等，临界状态"


def _fmt_decimal(value: Decimal) -> str:
    return f"{value:.4f}"


def _fmt_signed(value: Decimal) -> str:
    return f"{value:+.4f}"
