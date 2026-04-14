from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from .account import AccountService, AccountSnapshot
from .config import create_trade_context


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "account":
        return _handle_account(args)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-lb",
        description="Longbridge quant trading helpers.",
    )
    subparsers = parser.add_subparsers(dest="command")

    account = subparsers.add_parser("account", help="Query account balances and stock positions.")
    account.add_argument("--currency", help="Optional currency filter, e.g. HKD, USD, CNH.")
    account.add_argument(
        "--symbols",
        nargs="+",
        help="Optional stock symbols, e.g. AAPL.US 700.HK.",
    )
    account.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    return parser


def _handle_account(args: argparse.Namespace) -> int:
    try:
        ctx = create_trade_context()
        service = AccountService(ctx)
        snapshot = service.get_account_snapshot(currency=args.currency, symbols=args.symbols)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_format_snapshot(snapshot))
    return 0


def _format_snapshot(snapshot: AccountSnapshot) -> str:
    lines: list[str] = []
    lines.append("Account Balances")
    lines.append("================")
    if snapshot.balances:
        for balance in snapshot.balances:
            lines.extend(_format_balance(balance))
    else:
        lines.append("No account balance data.")

    lines.append("")
    lines.append("Stock Positions")
    lines.append("===============")
    if snapshot.stock_positions:
        for position in snapshot.stock_positions:
            lines.append(_format_position(position))
    else:
        lines.append("No stock positions.")

    return "\n".join(lines)


def _format_balance(balance: dict[str, Any]) -> list[str]:
    lines = [
        f"- {balance.get('currency') or '-'}",
        f"  total_cash: {balance.get('total_cash')}",
        f"  net_assets: {balance.get('net_assets')}",
        f"  buy_power: {balance.get('buy_power')}",
        f"  risk: {balance.get('risk_level')} ({balance.get('risk_level_text')})",
    ]
    for cash in balance.get("cash_infos", []):
        lines.append(
            "  cash "
            f"{cash.get('currency')}: available={cash.get('available_cash')}, "
            f"withdraw={cash.get('withdraw_cash')}, frozen={cash.get('frozen_cash')}, "
            f"settling={cash.get('settling_cash')}"
        )
    for fee in balance.get("frozen_transaction_fees", []):
        lines.append(
            "  frozen_fee "
            f"{fee.get('currency')}: {fee.get('frozen_transaction_fee')}"
        )
    return lines


def _format_position(position: dict[str, Any]) -> str:
    return (
        f"- {position.get('symbol')} {position.get('symbol_name') or ''} "
        f"[{position.get('account_channel') or '-'}] "
        f"qty={position.get('quantity')} "
        f"available={position.get('available_quantity')} "
        f"cost={position.get('cost_price')} "
        f"{position.get('currency') or ''}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
