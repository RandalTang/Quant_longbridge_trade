from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional


RISK_LEVELS = {
    0: "safe",
    1: "medium_risk",
    2: "early_warning",
    3: "danger",
}


@dataclass(frozen=True)
class AccountSnapshot:
    balances: list[dict[str, Any]] = field(default_factory=list)
    stock_positions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "balances": self.balances,
            "stock_positions": self.stock_positions,
        }


class AccountService:
    def __init__(self, trade_context: Any) -> None:
        self._trade_context = trade_context

    def get_account_snapshot(
        self,
        currency: Optional[str] = None,
        symbols: Optional[Iterable[str]] = None,
    ) -> AccountSnapshot:
        balances = self.get_account_balances(currency=currency)
        positions = self.get_stock_positions(symbols=symbols)
        return AccountSnapshot(balances=balances, stock_positions=positions)

    def get_account_balances(self, currency: Optional[str] = None) -> list[dict[str, Any]]:
        balances = self._trade_context.account_balance(currency=currency)
        return [_normalize_account_balance(balance) for balance in balances]

    def get_stock_positions(self, symbols: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
        symbol_list = list(symbols) if symbols else None
        response = self._trade_context.stock_positions(symbols=symbol_list)

        rows: list[dict[str, Any]] = []
        for channel in _getattr(response, "channels", default=[]):
            account_channel = _stringify(_getattr(channel, "account_channel"))
            for position in _getattr(channel, "positions", default=[]):
                row = _normalize_stock_position(position)
                row["account_channel"] = account_channel
                rows.append(row)
        return rows


def _normalize_account_balance(balance: Any) -> dict[str, Any]:
    risk_level = _getattr(balance, "risk_level")
    risk_level_int = _safe_int(risk_level)

    return {
        "currency": _stringify(_getattr(balance, "currency")),
        "total_cash": _stringify(_getattr(balance, "total_cash")),
        "net_assets": _stringify(_getattr(balance, "net_assets")),
        "buy_power": _stringify(_getattr(balance, "buy_power")),
        "max_finance_amount": _stringify(_getattr(balance, "max_finance_amount")),
        "remaining_finance_amount": _stringify(_getattr(balance, "remaining_finance_amount")),
        "init_margin": _stringify(_getattr(balance, "init_margin")),
        "maintenance_margin": _stringify(_getattr(balance, "maintenance_margin")),
        "margin_call": _stringify(_getattr(balance, "margin_call")),
        "risk_level": risk_level_int,
        "risk_level_text": RISK_LEVELS.get(risk_level_int, "unknown"),
        "cash_infos": [
            {
                "currency": _stringify(_getattr(info, "currency")),
                "available_cash": _stringify(_getattr(info, "available_cash")),
                "withdraw_cash": _stringify(_getattr(info, "withdraw_cash")),
                "frozen_cash": _stringify(_getattr(info, "frozen_cash")),
                "settling_cash": _stringify(_getattr(info, "settling_cash")),
            }
            for info in _getattr(balance, "cash_infos", default=[])
        ],
        "frozen_transaction_fees": [
            {
                "currency": _stringify(_getattr(fee, "currency")),
                "frozen_transaction_fee": _stringify(_getattr(fee, "frozen_transaction_fee")),
            }
            for fee in _getattr(balance, "frozen_transaction_fees", default=[])
        ],
    }


def _normalize_stock_position(position: Any) -> dict[str, Any]:
    return {
        "symbol": _stringify(_getattr(position, "symbol")),
        "symbol_name": _stringify(_getattr(position, "symbol_name")),
        "market": _stringify(_getattr(position, "market")),
        "currency": _stringify(_getattr(position, "currency")),
        "quantity": _stringify(_getattr(position, "quantity")),
        "available_quantity": _stringify(_getattr(position, "available_quantity")),
        "init_quantity": _stringify(_getattr(position, "init_quantity")),
        "cost_price": _stringify(_getattr(position, "cost_price")),
    }


def _getattr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return getattr(obj, name, default)


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)
