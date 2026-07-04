from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class DailyCandle:
    """日线 K 线。所有券商实现都要转成这个结构。"""

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class QuoteSnapshot:
    """单次实时报价快照。所有券商实现都要转成这个结构。"""

    symbol: str
    last_done: Decimal
    prev_close: Optional[Decimal]
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    timestamp: Optional[str]


@dataclass(frozen=True)
class AccountSnapshot:
    balances: list[dict[str, Any]] = field(default_factory=list)
    stock_positions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "balances": self.balances,
            "stock_positions": self.stock_positions,
        }


class Broker(ABC):
    """统一的券商接口。

    策略、监控、调度层只依赖这个接口，不接触任何券商 SDK。
    新接一家券商（IBKR、嘉信等）时，在 brokers/ 下新建目录实现这些方法，
    并在 brokers/__init__.py 的 create_broker 里注册即可。
    """

    name: str = "unknown"

    @abstractmethod
    def get_daily_candles(
        self,
        symbol: str,
        count: int = 300,
        adjust_type: str = "forward",
    ) -> list[DailyCandle]:
        """拉取日线 K 线，按时间升序返回。adjust_type: forward=前复权, none=不复权。"""

    @abstractmethod
    def get_quote(self, symbol: str) -> QuoteSnapshot:
        """拉取单个标的的最新报价。"""

    @abstractmethod
    def get_account_balances(self, currency: Optional[str] = None) -> list[dict[str, Any]]:
        """查询账户资金，返回归一化后的 dict 列表。"""

    @abstractmethod
    def get_stock_positions(self, symbols: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
        """查询股票持仓，返回归一化后的 dict 列表。

        每条至少包含：symbol, symbol_name, currency, quantity,
        available_quantity, cost_price。
        """

    def get_account_snapshot(
        self,
        currency: Optional[str] = None,
        symbols: Optional[Iterable[str]] = None,
    ) -> AccountSnapshot:
        return AccountSnapshot(
            balances=self.get_account_balances(currency=currency),
            stock_positions=self.get_stock_positions(symbols=symbols),
        )
