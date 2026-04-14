from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from time import monotonic, sleep
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class QuoteSnapshot:
    """单次行情快照：Longbridge 返回一组对象，这里只保留监控需要的字段。"""

    symbol: str
    last_done: Decimal
    prev_close: Optional[Decimal]
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    timestamp: Optional[str]


@dataclass(frozen=True)
class AlertEvent:
    """提醒事件：某条规则被触发后生成，后续可以扩展成邮件/Telegram/飞书通知。"""

    rule_name: str
    symbol: str
    message: str
    price: Decimal
    value: Optional[Decimal]
    triggered_at: datetime


@dataclass
class AlertRule:
    """单条提醒规则。

    cooldown_seconds 是冷却时间：同一条规则触发后，在冷却期内不会重复提醒。
    例如价格一直大于 55，如果没有冷却时间，程序每 10 秒都会提醒一次。
    """

    name: str
    evaluate: Callable[[QuoteSnapshot, "MonitorState"], Optional[tuple[str, Optional[Decimal]]]]
    cooldown_seconds: int = 600
    last_triggered_at: Optional[float] = None

    def maybe_trigger(self, quote: QuoteSnapshot, state: "MonitorState") -> Optional[AlertEvent]:
        now = monotonic()
        if self.last_triggered_at is not None:
            if now - self.last_triggered_at < self.cooldown_seconds:
                return None

        result = self.evaluate(quote, state)
        if result is None:
            return None

        message, value = result
        self.last_triggered_at = now
        return AlertEvent(
            rule_name=self.name,
            symbol=quote.symbol,
            message=message,
            price=quote.last_done,
            value=value,
            triggered_at=datetime.now(timezone.utc),
        )


class MonitorState:
    """监控状态。

    price_points 保存最近 window_seconds 秒内的价格，用来计算窗口涨跌幅。
    intraday_high 是监控启动后的最高价，用来计算从高点回撤多少。
    """

    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self.price_points: deque[tuple[float, Decimal]] = deque()
        self.intraday_high: Optional[Decimal] = None

    def update(self, quote: QuoteSnapshot) -> None:
        now = monotonic()
        self.price_points.append((now, quote.last_done))

        # 只保留最近 window_seconds 秒的数据，过旧价格会被移出窗口。
        cutoff = now - self.window_seconds
        while self.price_points and self.price_points[0][0] < cutoff:
            self.price_points.popleft()

        # 记录监控启动后的最高价。注意这里不是交易所日内最高价，而是本程序启动后的最高价。
        if self.intraday_high is None or quote.last_done > self.intraday_high:
            self.intraday_high = quote.last_done

    def pct_change(self) -> Optional[Decimal]:
        """计算窗口涨跌幅：窗口最后一个价格相对窗口第一个价格的百分比变化。"""

        if len(self.price_points) < 2:
            return None

        first_price = self.price_points[0][1]
        last_price = self.price_points[-1][1]
        if first_price == 0:
            return None
        return (last_price - first_price) / first_price * Decimal("100")

    def drawdown_from_high(self, price: Decimal) -> Optional[Decimal]:
        """计算从监控期间最高价到当前价的回撤百分比，通常是 0 或负数。"""

        if self.intraday_high is None or self.intraday_high == 0:
            return None
        return (price - self.intraday_high) / self.intraday_high * Decimal("100")


class QuoteMonitor:
    """简单行情监控器。

    第一版采用轮询：每隔 interval_seconds 秒请求一次最新行情。
    后续如果要更实时，可以把 fetch_quote 替换为 Longbridge 订阅行情。
    """

    def __init__(
        self,
        quote_context: Any,
        symbol: str,
        rules: list[AlertRule],
        interval_seconds: int = 10,
        window_seconds: int = 300,
    ) -> None:
        self._quote_context = quote_context
        self._symbol = symbol
        self._rules = rules
        self._interval_seconds = interval_seconds
        self._state = MonitorState(window_seconds=window_seconds)

    def run(self, max_ticks: Optional[int] = None) -> None:
        """启动监控循环。max_ticks 只用于测试，不传则一直运行直到 Ctrl+C。"""

        tick_count = 0
        while max_ticks is None or tick_count < max_ticks:
            quote = self.fetch_quote()
            self._state.update(quote)
            print(_format_tick(quote, self._state))

            for rule in self._rules:
                event = rule.maybe_trigger(quote, self._state)
                if event:
                    print(_format_alert(event))

            tick_count += 1
            if max_ticks is None or tick_count < max_ticks:
                sleep(self._interval_seconds)

    def fetch_quote(self) -> QuoteSnapshot:
        """从 Longbridge 拉取一个标的的最新报价。"""

        quotes = self._quote_context.quote([self._symbol])
        if not quotes:
            raise RuntimeError(f"No quote returned for {self._symbol}.")
        return normalize_quote(quotes[0])


def build_rules(
    price_above: Optional[str] = None,
    price_below: Optional[str] = None,
    pct_change_above: Optional[str] = None,
    pct_change_below: Optional[str] = None,
    drawdown_below: Optional[str] = None,
    cooldown_seconds: int = 600,
) -> list[AlertRule]:
    """根据 CLI 参数构建提醒规则。

    price_above / price_below：最新价高于或低于阈值。
    pct_change_above / pct_change_below：窗口涨跌幅高于或低于阈值，单位是百分比。
    drawdown_below：当前价相对监控启动后最高价的回撤低于阈值，例如 -3 表示回撤超过 3%。
    """

    rules: list[AlertRule] = []

    if price_above is not None:
        threshold = _decimal(price_above, "price_above")
        rules.append(
            AlertRule(
                name=f"price_above_{threshold}",
                cooldown_seconds=cooldown_seconds,
                evaluate=lambda quote, _state, t=threshold: (
                    (f"price {quote.last_done} is above {t}", quote.last_done)
                    if quote.last_done > t
                    else None
                ),
            )
        )

    if price_below is not None:
        threshold = _decimal(price_below, "price_below")
        rules.append(
            AlertRule(
                name=f"price_below_{threshold}",
                cooldown_seconds=cooldown_seconds,
                evaluate=lambda quote, _state, t=threshold: (
                    (f"price {quote.last_done} is below {t}", quote.last_done)
                    if quote.last_done < t
                    else None
                ),
            )
        )

    if pct_change_above is not None:
        threshold = _decimal(pct_change_above, "pct_change_above")
        rules.append(
            AlertRule(
                name=f"pct_change_above_{threshold}",
                cooldown_seconds=cooldown_seconds,
                evaluate=lambda _quote, state, t=threshold: _pct_change_above(state, t),
            )
        )

    if pct_change_below is not None:
        threshold = _decimal(pct_change_below, "pct_change_below")
        rules.append(
            AlertRule(
                name=f"pct_change_below_{threshold}",
                cooldown_seconds=cooldown_seconds,
                evaluate=lambda _quote, state, t=threshold: _pct_change_below(state, t),
            )
        )

    if drawdown_below is not None:
        threshold = _decimal(drawdown_below, "drawdown_below")
        rules.append(
            AlertRule(
                name=f"drawdown_below_{threshold}",
                cooldown_seconds=cooldown_seconds,
                evaluate=lambda quote, state, t=threshold: _drawdown_below(quote, state, t),
            )
        )

    return rules


def normalize_quote(quote: Any) -> QuoteSnapshot:
    """把 Longbridge SDK 的行情对象转成我们自己的 QuoteSnapshot。"""

    symbol = str(_getattr(quote, "symbol") or "")
    last_done = _decimal(_getattr(quote, "last_done"), "last_done")
    return QuoteSnapshot(
        symbol=symbol,
        last_done=last_done,
        prev_close=_optional_decimal(_getattr(quote, "prev_close")),
        open=_optional_decimal(_getattr(quote, "open")),
        high=_optional_decimal(_getattr(quote, "high")),
        low=_optional_decimal(_getattr(quote, "low")),
        timestamp=_stringify(_getattr(quote, "timestamp")),
    )


def _pct_change_above(state: MonitorState, threshold: Decimal) -> Optional[tuple[str, Optional[Decimal]]]:
    value = state.pct_change()
    if value is not None and value > threshold:
        return f"window change {value:.2f}% is above {threshold}%", value
    return None


def _pct_change_below(state: MonitorState, threshold: Decimal) -> Optional[tuple[str, Optional[Decimal]]]:
    value = state.pct_change()
    if value is not None and value < threshold:
        return f"window change {value:.2f}% is below {threshold}%", value
    return None


def _drawdown_below(
    quote: QuoteSnapshot,
    state: MonitorState,
    threshold: Decimal,
) -> Optional[tuple[str, Optional[Decimal]]]:
    value = state.drawdown_from_high(quote.last_done)
    if value is not None and value < threshold:
        return f"drawdown from monitor high {value:.2f}% is below {threshold}%", value
    return None


def _format_tick(quote: QuoteSnapshot, state: MonitorState) -> str:
    change = state.pct_change()
    drawdown = state.drawdown_from_high(quote.last_done)
    change_text = "-" if change is None else f"{change:.2f}%"
    drawdown_text = "-" if drawdown is None else f"{drawdown:.2f}%"
    return (
        f"[{datetime.now().isoformat(timespec='seconds')}] "
        f"{quote.symbol} price={quote.last_done} "
        f"window_change={change_text} drawdown={drawdown_text}"
    )


def _format_alert(event: AlertEvent) -> str:
    return (
        f"ALERT {event.triggered_at.isoformat(timespec='seconds')} "
        f"{event.symbol} {event.rule_name}: {event.message}"
    )


def _getattr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return getattr(obj, name, default)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number, got {value!r}.") from exc


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return _decimal(value, "optional_decimal")


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)
