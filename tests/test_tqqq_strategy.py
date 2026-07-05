"""TQQQ EMA5/EMA30 策略 + 重构后 Broker 链路的回归测试。

不需要长桥 SDK、API key 和网络：用一个假 Broker（FakeBroker）喂固定 K 线，
验证策略层纯函数和服务层（确认/预览/SQQQ 死叉）在新接口下都正常工作。

直接运行（只跑本地断言，不发飞书）：

    python tests/test_tqqq_strategy.py

跑完断言后把策略生成的真实消息发到飞书（需要 .env 配好 FEISHU_WEBHOOK_URL）：

    python tests/test_tqqq_strategy.py --notify

或者用 pytest（如果装了）：

    pytest tests/test_tqqq_strategy.py -v
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_longbridge_trade.brokers import create_broker  # noqa: E402
from quant_longbridge_trade.brokers.base import (  # noqa: E402
    Broker,
    DailyCandle,
    QuoteSnapshot,
)
from quant_longbridge_trade.ema_service import (  # noqa: E402
    check_ema_preview_signal,
    check_ema_signal,
    check_sqqq_death_cross,
)
from quant_longbridge_trade.strategies import (  # noqa: E402
    SIGNAL_BUY,
    SIGNAL_BUY_PREVIEW,
    SIGNAL_NONE,
    SIGNAL_NONE_PREVIEW,
    SIGNAL_SELL,
    evaluate_ema_cross,
)

BASE_DATE = datetime(2026, 1, 1)

# 这两组序列是用真实 EMA 代码算出来的，保证穿越正好发生在最后一根 K 线：
# 金叉：先跌 40 天（100→61），再每天 +3 涨 6 天，最后一天 EMA5 上穿 EMA30
GOLDEN_CROSS_CLOSES = [100 - i for i in range(40)] + [61 + 3 * j for j in range(1, 7)]
# 死叉：先涨 40 天（60→99），再每天 -3 跌 6 天，最后一天 EMA5 下穿 EMA30
DEATH_CROSS_CLOSES = [60 + i for i in range(40)] + [99 - 3 * j for j in range(1, 7)]


def make_candles(closes: Iterable, symbol: str = "TQQQ.US") -> list[DailyCandle]:
    return [
        DailyCandle(
            symbol=symbol,
            timestamp=BASE_DATE + timedelta(days=i),
            open=c,
            high=c,
            low=c,
            close=c,
            volume=100,
        )
        for i, c in enumerate(Decimal(str(x)) for x in closes)
    ]


class FakeBroker(Broker):
    """假券商：返回固定 K 线和报价，用来测策略/服务层，不碰任何 SDK。"""

    name = "fake"

    def __init__(
        self,
        candles: list[DailyCandle],
        quote: Optional[QuoteSnapshot] = None,
        positions: Optional[list[dict]] = None,
    ) -> None:
        self._candles = candles
        self._quote = quote
        self._positions = positions if positions is not None else [
            {"quantity": "100", "available_quantity": "100"}
        ]

    def get_daily_candles(self, symbol, count=300, adjust_type="forward"):
        return list(self._candles)

    def get_quote(self, symbol):
        if self._quote is None:
            raise RuntimeError("FakeBroker has no quote configured")
        return self._quote

    def get_account_balances(self, currency=None):
        return []

    def get_stock_positions(self, symbols=None):
        return list(self._positions)


def _quote(price, timestamp: str, symbol: str = "TQQQ.US") -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        last_done=Decimal(str(price)),
        prev_close=None,
        open=None,
        high=None,
        low=None,
        timestamp=timestamp,
    )


# ---- 策略层：纯函数 ----

def test_golden_cross_gives_buy():
    signal = evaluate_ema_cross(make_candles(GOLDEN_CROSS_CLOSES), "TQQQ.US")
    assert signal.signal == SIGNAL_BUY, signal.signal
    assert signal.fast_ema > signal.slow_ema
    assert signal.previous_fast_ema <= signal.previous_slow_ema
    assert signal.dedupe_key == f"TQQQ.US:{signal.trade_date}:EMA:CONFIRMED:{SIGNAL_BUY}"


def test_death_cross_gives_sell():
    signal = evaluate_ema_cross(make_candles(DEATH_CROSS_CLOSES), "TQQQ.US")
    assert signal.signal == SIGNAL_SELL, signal.signal
    assert signal.fast_ema < signal.slow_ema


def test_day_before_cross_is_no_signal():
    signal = evaluate_ema_cross(make_candles(GOLDEN_CROSS_CLOSES[:-1]), "TQQQ.US")
    assert signal.signal == SIGNAL_NONE, signal.signal


def test_diff_indicators():
    # 金叉当天：今日差值为正、昨日差值 <= 0，快线在上方
    signal = evaluate_ema_cross(make_candles(GOLDEN_CROSS_CLOSES), "TQQQ.US")
    assert signal.fast_slow_diff == signal.fast_ema - signal.slow_ema
    assert signal.previous_fast_slow_diff == signal.previous_fast_ema - signal.previous_slow_ema
    assert signal.fast_slow_diff > 0
    assert signal.previous_fast_slow_diff <= 0
    assert signal.higher_line == "EMA5", signal.higher_line

    # 死叉当天：今日差值为负，慢线在上方
    signal = evaluate_ema_cross(make_candles(DEATH_CROSS_CLOSES), "TQQQ.US")
    assert signal.fast_slow_diff < 0
    assert signal.higher_line == "EMA30", signal.higher_line


def test_invalid_params_raise():
    candles = make_candles(GOLDEN_CROSS_CLOSES)
    for fast, slow in [(0, 30), (30, 5), (5, 5)]:
        try:
            evaluate_ema_cross(candles, "TQQQ.US", fast=fast, slow=slow)
            raise AssertionError(f"fast={fast} slow={slow} should have raised")
        except ValueError:
            pass
    try:
        evaluate_ema_cross(candles[:10], "TQQQ.US")
        raise AssertionError("insufficient candles should have raised")
    except ValueError:
        pass


# ---- 服务层：走 Broker 接口 ----

def test_confirmed_signal_through_broker():
    broker = FakeBroker(make_candles(GOLDEN_CROSS_CLOSES))
    result = check_ema_signal(broker, symbol="TQQQ.US")
    assert result.signal.signal == SIGNAL_BUY
    assert "EMA5 上穿 EMA30" in result.message
    assert "当前持仓：100 股，可用 100" in result.message
    assert "TQQQ EMA 策略确认" in result.message
    assert "今日快慢差：+" in result.message
    assert "昨日快慢差：" in result.message
    assert "当前在上方：EMA5" in result.message


def test_preview_replaces_today_close():
    # 差一天金叉的序列；实时价大涨，替换今日收盘后应触发 BUY_PREVIEW
    candles = make_candles(GOLDEN_CROSS_CLOSES[:-1])
    today = candles[-1].timestamp.date().isoformat()
    broker = FakeBroker(candles, quote=_quote(Decimal("76") * Decimal("1.15"), today))
    result = check_ema_preview_signal(broker, symbol="TQQQ.US")
    assert result.signal.mode == "PREVIEW"
    assert result.signal.signal == SIGNAL_BUY_PREVIEW, result.signal.signal
    assert "TQQQ EMA 策略预警" in result.message


def test_preview_appends_new_day_candle():
    # 报价日期比最后一根 K 线新一天：应追加一根新 K 线再计算
    candles = make_candles(GOLDEN_CROSS_CLOSES[:-1])
    next_day = (candles[-1].timestamp + timedelta(days=1)).date().isoformat()
    broker = FakeBroker(candles, quote=_quote(Decimal("76") * Decimal("1.15"), next_day))
    result = check_ema_preview_signal(broker, symbol="TQQQ.US")
    assert result.signal.signal == SIGNAL_BUY_PREVIEW, result.signal.signal
    assert result.signal.trade_date == next_day


def test_preview_no_cross_stays_quiet():
    candles = make_candles(GOLDEN_CROSS_CLOSES[:-1])
    today = candles[-1].timestamp.date().isoformat()
    broker = FakeBroker(candles, quote=_quote("76", today))  # 价格没变
    result = check_ema_preview_signal(broker, symbol="TQQQ.US")
    assert result.signal.signal == SIGNAL_NONE_PREVIEW, result.signal.signal
    assert not result.signal.has_signal


def test_sqqq_death_cross_message():
    closes = DEATH_CROSS_CLOSES
    broker = FakeBroker(make_candles(closes, symbol="SQQQ.US"))
    result = check_sqqq_death_cross(broker, symbol="SQQQ.US")
    assert result.signal.signal == SIGNAL_SELL
    assert "SQQQ EMA 死叉确认" in result.message
    assert "考虑先卖出空仓" in result.message


def test_position_query_failure_is_tolerated():
    class BrokenPositionBroker(FakeBroker):
        def get_stock_positions(self, symbols=None):
            raise RuntimeError("boom")

    broker = BrokenPositionBroker(make_candles(GOLDEN_CROSS_CLOSES))
    result = check_ema_signal(broker, symbol="TQQQ.US")
    assert result.signal.signal == SIGNAL_BUY  # 持仓查询失败不影响信号
    assert "查询失败" in result.current_position


# ---- 工厂 ----

def test_create_broker_rejects_unknown():
    try:
        create_broker("ibkr")
        raise AssertionError("should have raised")
    except ValueError as exc:
        assert "Unsupported broker" in str(exc)


def send_test_messages_to_feishu() -> bool:
    """把三条代表性的策略消息（金叉确认 / 金叉预览 / SQQQ 死叉）发到飞书。

    消息由真实的策略 + 服务层代码生成，只是数据来自 FakeBroker，
    每条都加了【测试】前缀，避免和真实提醒混淆。
    """
    from quant_longbridge_trade.notifier import FeishuNotifier

    try:
        notifier = FeishuNotifier.from_env()
    except Exception as exc:
        print(f"[飞书] 读取配置失败：{exc}", file=sys.stderr)
        print("[飞书] 请检查 .env 里的 FEISHU_WEBHOOK_URL。", file=sys.stderr)
        return False

    buy_result = check_ema_signal(
        FakeBroker(make_candles(GOLDEN_CROSS_CLOSES)), symbol="TQQQ.US"
    )

    preview_candles = make_candles(GOLDEN_CROSS_CLOSES[:-1])
    preview_today = preview_candles[-1].timestamp.date().isoformat()
    preview_result = check_ema_preview_signal(
        FakeBroker(
            preview_candles,
            quote=_quote(Decimal("76") * Decimal("1.15"), preview_today),
        ),
        symbol="TQQQ.US",
    )

    sqqq_result = check_sqqq_death_cross(
        FakeBroker(make_candles(DEATH_CROSS_CLOSES, symbol="SQQQ.US")),
        symbol="SQQQ.US",
    )

    messages = [
        ("金叉确认 BUY", buy_result.message),
        ("金叉预览 BUY_PREVIEW", preview_result.message),
        ("SQQQ 死叉 SELL", sqqq_result.message),
    ]

    ok = True
    for label, message in messages:
        try:
            notifier.send_text(f"【测试】以下为策略测试消息（假数据），请勿操作\n\n{message}")
            print(f"[飞书] 已发送：{label}")
        except Exception as exc:
            ok = False
            print(f"[飞书] 发送失败（{label}）：{exc}", file=sys.stderr)
    return ok


def main() -> int:
    notify = "--notify" in sys.argv

    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception:
            failed += 1
            print(f"[FAIL] {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")

    if failed:
        if notify:
            print("断言未全部通过，跳过飞书发送。", file=sys.stderr)
        return 1

    if notify:
        print("\n断言全部通过，开始发送测试消息到飞书...")
        if not send_test_messages_to_feishu():
            return 1
        print("发送完成，去飞书群里核对三条消息的格式。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
