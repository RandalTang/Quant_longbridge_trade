from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from ...config import load_local_env
from ..base import Broker, DailyCandle, QuoteSnapshot

REQUIRED_API_KEY_ENV = (
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
)

RISK_LEVELS = {
    0: "safe",
    1: "medium_risk",
    2: "early_warning",
    3: "danger",
}


def missing_api_key_env() -> list[str]:
    load_local_env()
    return [name for name in REQUIRED_API_KEY_ENV if not os.getenv(name)]


class LongbridgeBroker(Broker):
    name = "longbridge"

    def __init__(self) -> None:
        self._config: Any = None
        self._quote_context: Any = None
        self._trade_context: Any = None

    # ---- 行情 ----

    def get_daily_candles(
        self,
        symbol: str,
        count: int = 300,
        adjust_type: str = "forward",
    ) -> list[DailyCandle]:
        openapi = _openapi()
        sdk_adjust_type = _resolve_adjust_type(openapi.AdjustType, adjust_type)
        candles = self._quote_ctx().candlesticks(symbol, openapi.Period.Day, count, sdk_adjust_type)
        normalized = [_normalize_candle(symbol, candle) for candle in candles]
        normalized.sort(key=lambda item: item.timestamp)
        return normalized

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        quotes = self._quote_ctx().quote([symbol])
        if not quotes:
            raise RuntimeError(f"No quote returned for {symbol}.")
        return _normalize_quote(quotes[0])

    # ---- 账户 ----

    def get_account_balances(self, currency: Optional[str] = None) -> list[dict[str, Any]]:
        balances = self._trade_ctx().account_balance(currency=currency)
        return [_normalize_account_balance(balance) for balance in balances]

    def get_stock_positions(self, symbols: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
        symbol_list = list(symbols) if symbols else None
        response = self._trade_ctx().stock_positions(symbols=symbol_list)

        rows: list[dict[str, Any]] = []
        for channel in _getattr(response, "channels", default=[]):
            account_channel = _stringify(_getattr(channel, "account_channel"))
            for position in _getattr(channel, "positions", default=[]):
                row = _normalize_stock_position(position)
                row["account_channel"] = account_channel
                rows.append(row)
        return rows

    # ---- SDK 上下文（懒加载，只在第一次用到时创建）----

    def _sdk_config(self) -> Any:
        if self._config is None:
            missing = missing_api_key_env()
            if missing:
                joined = ", ".join(missing)
                raise RuntimeError(
                    "Longbridge API key environment is incomplete. "
                    f"Missing: {joined}. See .env.example for the expected variables."
                )
            self._config = _openapi().Config.from_apikey_env()
        return self._config

    def _quote_ctx(self) -> Any:
        if self._quote_context is None:
            self._quote_context = _openapi().QuoteContext(self._sdk_config())
        return self._quote_context

    def _trade_ctx(self) -> Any:
        if self._trade_context is None:
            self._trade_context = _openapi().TradeContext(self._sdk_config())
        return self._trade_context


def _openapi() -> Any:
    try:
        from longbridge import openapi
    except ImportError as exc:
        raise RuntimeError(
            "The longbridge SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc
    return openapi


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


def _normalize_quote(quote: Any) -> QuoteSnapshot:
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
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)
