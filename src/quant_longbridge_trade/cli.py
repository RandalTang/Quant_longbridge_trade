from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from .account import AccountService, AccountSnapshot
from .config import create_quote_context, create_trade_context
from .daemon import DaemonConfig, SignalDaemon
from .ema_service import (
    check_ema_preview_signal,
    check_ema_signal,
    check_sqqq_death_cross,
    format_secondary_signal_status,
)
from .notifier import FeishuNotifier
from .monitor import QuoteMonitor, build_rules
from .state import JsonStateStore


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "account":
        return _handle_account(args)
    if args.command == "monitor":
        return _handle_monitor(args)
    if args.command == "signal":
        return _handle_signal(args)
    if args.command == "daemon":
        return _handle_daemon(args)

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

    monitor = subparsers.add_parser("monitor", help="监控某个标的行情，触发规则时打印提醒。")
    monitor.add_argument(
        "--symbol",
        default="TQQQ.US",
        help="要监控的股票/ETF 代码，例如 TQQQ.US。默认：TQQQ.US。",
    )
    monitor.add_argument(
        "--interval-seconds",
        type=int,
        default=10,
        help="轮询间隔，单位秒；每隔多久向 Longbridge 拉一次最新报价。默认：10。",
    )
    monitor.add_argument(
        "--window-seconds",
        type=int,
        default=300,
        help="涨跌幅计算窗口，单位秒；300 表示用最近 5 分钟价格算 window_change。默认：300。",
    )
    monitor.add_argument(
        "--cooldown-seconds",
        type=int,
        default=600,
        help="同一条规则的提醒冷却时间，单位秒；避免价格持续满足条件时刷屏。默认：600。",
    )
    monitor.add_argument("--price-above", help="价格上限提醒；最新价大于这个值时触发，例如 55。")
    monitor.add_argument("--price-below", help="价格下限提醒；最新价小于这个值时触发，例如 48。")
    monitor.add_argument(
        "--pct-change-above",
        help="窗口涨幅提醒；最近 window-seconds 内涨幅大于这个百分比时触发，例如 2 表示上涨超过 2%%。",
    )
    monitor.add_argument(
        "--pct-change-below",
        help="窗口跌幅提醒；最近 window-seconds 内涨跌幅小于这个百分比时触发，例如 -2 表示下跌超过 2%%。",
    )
    monitor.add_argument(
        "--drawdown-below",
        help="回撤提醒；当前价相对监控启动后的最高价回撤低于该百分比时触发，例如 -3 表示回撤超过 3%%。",
    )
    monitor.add_argument(
        "--max-ticks",
        type=int,
        help="最多轮询次数；测试用，达到次数后自动退出。不传则一直运行。",
    )

    signal = subparsers.add_parser("signal", help="检查日线 EMA 策略信号，并可发送飞书提醒。")
    _add_ema_signal_arguments(signal)
    signal.add_argument("--preview", action="store_true", help="用实时价模拟今日收盘，检查收盘前预警信号。")
    signal.add_argument("--watch-sqqq-death-cross", action="store_true", help="额外检查 SQQQ EMA 死叉；如果触发则提醒空仓。")
    signal.add_argument("--sqqq-symbol", default="SQQQ.US", help="SQQQ 标的代码。默认：SQQQ.US。")
    signal.add_argument("--notify", action="store_true", help="有买卖信号时发送飞书提醒。")
    signal.add_argument("--notify-no-signal", action="store_true", help="无信号时也发送飞书提醒。")
    signal.add_argument("--notify-errors", action="store_true", help="检查失败时也发送飞书错误提醒。")
    signal.add_argument("--no-dedupe", action="store_true", help="关闭去重；默认同一天同信号只提醒一次。")

    daemon = subparsers.add_parser("daemon", help="常驻运行日线 EMA 策略检查，适合部署到云服务器。")
    _add_ema_signal_arguments(daemon)
    daemon.add_argument("--run-at", help="兼容旧参数：只设置确认检查时间，格式 HH:MM。")
    daemon.add_argument("--preclose-at", default="15:55", help="美股收盘前预警时间，格式 HH:MM。默认：15:55。")
    daemon.add_argument("--confirm-at", default="16:10", help="美股收盘后确认时间，格式 HH:MM。默认：16:10。")
    daemon.add_argument("--market-timezone", default="America/New_York", help="市场时区。默认：America/New_York。")
    daemon.add_argument("--timezone", help="兼容旧参数；如果传入，会覆盖 --market-timezone。")
    daemon.add_argument("--disable-preclose-warning", action="store_true", help="关闭收盘前 5 分钟预警。")
    daemon.add_argument("--watch-sqqq-death-cross", action="store_true", help="额外检查 SQQQ EMA 死叉；如果触发则提醒空仓。")
    daemon.add_argument("--sqqq-symbol", default="SQQQ.US", help="SQQQ 标的代码。默认：SQQQ.US。")
    daemon.add_argument("--poll-seconds", type=int, default=60, help="daemon 醒来检查的间隔秒数。默认：60。")
    daemon.add_argument("--notify-no-signal", action="store_true", help="无信号时也每天发送一次飞书心跳。")
    daemon.add_argument("--no-notify-errors", action="store_true", help="关闭异常飞书提醒。默认开启。")
    daemon.add_argument("--error-cooldown-seconds", type=int, default=3600, help="相同异常的飞书提醒冷却时间。默认：3600。")

    return parser


def _add_ema_signal_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol", default="TQQQ.US", help="Longbridge 标的代码。默认：TQQQ.US。")
    parser.add_argument("--fast", type=int, default=5, help="EMA 快线周期。默认：5。")
    parser.add_argument("--slow", type=int, default=30, help="EMA 慢线周期。默认：30。")
    parser.add_argument("--candle-count", type=int, default=300, help="拉取最近多少根日线。默认：300。")
    parser.add_argument(
        "--adjust-type",
        default="forward",
        choices=["forward", "none"],
        help="K 线复权方式。forward=前复权，none=不复权。默认：forward。",
    )
    parser.add_argument("--state-path", default=".data/alert_state.json", help="提醒去重状态文件路径。")


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


def _handle_monitor(args: argparse.Namespace) -> int:
    try:
        rules = build_rules(
            price_above=args.price_above,
            price_below=args.price_below,
            pct_change_above=args.pct_change_above,
            pct_change_below=args.pct_change_below,
            drawdown_below=args.drawdown_below,
            cooldown_seconds=args.cooldown_seconds,
        )
        if not rules:
            print(
                "Error: at least one monitor rule is required. "
                "Use --price-above, --price-below, --pct-change-above, "
                "--pct-change-below, or --drawdown-below.",
                file=sys.stderr,
            )
            return 2

        ctx = create_quote_context()
        monitor = QuoteMonitor(
            quote_context=ctx,
            symbol=args.symbol,
            rules=rules,
            interval_seconds=args.interval_seconds,
            window_seconds=args.window_seconds,
        )
        monitor.run(max_ticks=args.max_ticks)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    return 0


def _handle_signal(args: argparse.Namespace) -> int:
    try:
        checker = check_ema_preview_signal if args.preview else check_ema_signal
        result = checker(
            quote_context=create_quote_context(),
            trade_context=create_trade_context(),
            symbol=args.symbol,
            fast=args.fast,
            slow=args.slow,
            candle_count=args.candle_count,
            adjust_type=args.adjust_type,
        )
        print(result.message)

        sqqq_result = None
        if args.watch_sqqq_death_cross:
            sqqq_result = check_sqqq_death_cross(
                quote_context=create_quote_context(),
                trade_context=create_trade_context(),
                symbol=args.sqqq_symbol,
                fast=args.fast,
                slow=args.slow,
                candle_count=args.candle_count,
                adjust_type=args.adjust_type,
                preview=args.preview,
            )
            print("\n" + sqqq_result.message)

        notification_message = result.message
        if sqqq_result is not None:
            notification_message = "\n\n".join(
                [
                    result.message,
                    "---",
                    format_secondary_signal_status(sqqq_result, "SQQQ 补充状态"),
                ]
            )

        should_notify = args.notify and result.signal.has_signal
        should_notify = should_notify or args.notify_no_signal
        if should_notify:
            state = JsonStateStore(args.state_path)
            key = result.signal.dedupe_key
            if not args.no_dedupe and state.was_sent(key):
                print(f"Skip duplicated notification: {key}")
            else:
                FeishuNotifier.from_env().send_text(notification_message)
                if not args.no_dedupe:
                    state.mark_sent(key)
                print(f"Feishu notification sent: {key}")
        if sqqq_result is not None:
            if sqqq_result.signal.signal in {"SELL", "SELL_PREVIEW"} and (args.notify or args.notify_no_signal):
                key = f"{sqqq_result.signal.dedupe_key}:SQQQ_DEATH"
                state = JsonStateStore(args.state_path)
                if not args.no_dedupe and state.was_sent(key):
                    print(f"Skip duplicated SQQQ death notification: {key}")
                else:
                    FeishuNotifier.from_env().send_text(sqqq_result.message)
                    if not args.no_dedupe:
                        state.mark_sent(key)
                    print(f"Feishu SQQQ death notification sent: {key}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if args.notify_errors:
            _send_signal_error_notification(args, exc)
        return 2

    return 0


def _handle_daemon(args: argparse.Namespace) -> int:
    try:
        timezone = args.timezone or args.market_timezone
        confirm_at = args.run_at or args.confirm_at
        config = DaemonConfig(
            symbol=args.symbol,
            sqqq_symbol=args.sqqq_symbol,
            fast=args.fast,
            slow=args.slow,
            run_at=confirm_at,
            timezone=timezone,
            preclose_at=args.preclose_at,
            confirm_at=confirm_at,
            enable_preclose_warning=not args.disable_preclose_warning,
            poll_seconds=args.poll_seconds,
            candle_count=args.candle_count,
            adjust_type=args.adjust_type,
            notify_no_signal=args.notify_no_signal,
            watch_sqqq_death_cross=args.watch_sqqq_death_cross,
            notify_errors=not args.no_notify_errors,
            error_cooldown_seconds=args.error_cooldown_seconds,
            state_path=args.state_path,
        )
        SignalDaemon(config).run_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    return 0


def _send_signal_error_notification(args: argparse.Namespace, exc: Exception) -> None:
    message = "\n".join(
        [
            "Longbridge 策略检查失败",
            "",
            f"标的：{args.symbol}",
            f"策略：EMA{args.fast}/EMA{args.slow}",
            "",
            "可能原因：",
            "- LONGBRIDGE_ACCESS_TOKEN 过期或无效",
            "- LONGBRIDGE_APP_KEY / LONGBRIDGE_APP_SECRET / LONGBRIDGE_ACCESS_TOKEN 缺失",
            "- 行情权限不足",
            "- 网络或 Longbridge OpenAPI 暂时不可用",
            "",
            f"错误：{exc}",
        ]
    )
    try:
        FeishuNotifier.from_env().send_text(message)
        print("Feishu error notification sent.")
    except Exception as notify_exc:
        print(f"Failed to send Feishu error notification: {notify_exc}", file=sys.stderr)


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
