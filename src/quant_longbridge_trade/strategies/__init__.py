"""策略包。每个策略一个文件，纯函数：输入 K 线列表，输出带 dedupe_key 的信号 dataclass。

新增策略步骤：
1. 新建 strategies/<策略名>.py，照 ema_cross.py 的模式写 evaluate_xxx() + 信号 dataclass
2. 公共指标（EMA 等）放 indicators.py，不要在策略文件里重复实现
3. 在这里 re-export，服务层统一从 quant_longbridge_trade.strategies import
"""
from .ema_cross import (
    ACTION_SIGNALS,
    BUY_SIGNALS,
    SELL_SIGNALS,
    SIGNAL_BUY,
    SIGNAL_BUY_PREVIEW,
    SIGNAL_NONE,
    SIGNAL_NONE_PREVIEW,
    SIGNAL_SELL,
    SIGNAL_SELL_PREVIEW,
    EmaCrossSignal,
    ema_position_text,
    evaluate_ema_cross,
    format_signal_message,
)
from .indicators import ema

__all__ = [
    "ACTION_SIGNALS",
    "BUY_SIGNALS",
    "SELL_SIGNALS",
    "SIGNAL_BUY",
    "SIGNAL_BUY_PREVIEW",
    "SIGNAL_NONE",
    "SIGNAL_NONE_PREVIEW",
    "SIGNAL_SELL",
    "SIGNAL_SELL_PREVIEW",
    "EmaCrossSignal",
    "ema",
    "ema_position_text",
    "evaluate_ema_cross",
    "format_signal_message",
]
