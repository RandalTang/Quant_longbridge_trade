from __future__ import annotations

import hashlib
import traceback
from dataclasses import dataclass
from datetime import datetime
from time import sleep
from zoneinfo import ZoneInfo

from .config import create_quote_context, create_trade_context
from .ema_service import check_ema_signal
from .notifier import FeishuNotifier
from .state import JsonStateStore


@dataclass(frozen=True)
class DaemonConfig:
    symbol: str = "TQQQ.US"
    fast: int = 5
    slow: int = 30
    run_at: str = "06:00"
    timezone: str = "Asia/Singapore"
    poll_seconds: int = 60
    candle_count: int = 300
    adjust_type: str = "forward"
    notify_no_signal: bool = False
    notify_errors: bool = True
    error_cooldown_seconds: int = 3600
    state_path: str = ".data/alert_state.json"


class SignalDaemon:
    def __init__(self, config: DaemonConfig) -> None:
        self._config = config
        self._state = JsonStateStore(config.state_path)

    def run_forever(self) -> None:
        print(
            f"daemon started: symbol={self._config.symbol} run_at={self._config.run_at} "
            f"timezone={self._config.timezone}"
        )
        while True:
            try:
                if self._should_run_now():
                    self.run_once()
                    self._mark_checked_today()
            except Exception as exc:
                print(f"[{datetime.now().isoformat(timespec='seconds')}] daemon error: {exc}")
                if self._config.notify_errors:
                    self._notify_error(exc)
            sleep(self._config.poll_seconds)

    def run_once(self) -> None:
        quote_context = create_quote_context()
        trade_context = create_trade_context()
        notifier = FeishuNotifier.from_env()

        result = check_ema_signal(
            quote_context=quote_context,
            trade_context=trade_context,
            symbol=self._config.symbol,
            fast=self._config.fast,
            slow=self._config.slow,
            candle_count=self._config.candle_count,
            adjust_type=self._config.adjust_type,
        )

        now = datetime.now(ZoneInfo(self._config.timezone)).isoformat(timespec="seconds")
        print(f"[{now}] {result.signal.symbol} {result.signal.trade_date} {result.signal.signal}: {result.signal.reason}")

        if result.signal.has_signal:
            if self._state.was_sent(result.signal.dedupe_key):
                print(f"skip duplicated alert: {result.signal.dedupe_key}")
                return
            notifier.send_text(result.message)
            self._state.mark_sent(result.signal.dedupe_key)
            print(f"sent alert: {result.signal.dedupe_key}")
        elif self._config.notify_no_signal:
            key = f"{result.signal.symbol}:{result.signal.trade_date}:NO_SIGNAL:EMA"
            if not self._state.was_sent(key):
                notifier.send_text(result.message)
                self._state.mark_sent(key)
                print(f"sent heartbeat: {key}")

    def _should_run_now(self) -> bool:
        now = datetime.now(ZoneInfo(self._config.timezone))
        today_key = self._today_key(now)
        if self._state.get("last_daemon_check_date") == today_key:
            return False

        hour, minute = _parse_run_at(self._config.run_at)
        return now.hour > hour or (now.hour == hour and now.minute >= minute)

    def _mark_checked_today(self) -> None:
        now = datetime.now(ZoneInfo(self._config.timezone))
        self._state.set("last_daemon_check_date", self._today_key(now))

    def _today_key(self, now: datetime) -> str:
        return f"{self._config.symbol}:{now.date().isoformat()}:{self._config.run_at}"

    def _notify_error(self, exc: Exception) -> None:
        error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        error_hash = hashlib.sha256(error_text.encode("utf-8")).hexdigest()[:16]
        last_error_key = f"last_error_alert_at:{error_hash}"
        now = datetime.now(ZoneInfo(self._config.timezone))
        last_sent_at = self._state.get(last_error_key)
        if last_sent_at:
            last_sent = datetime.fromisoformat(last_sent_at)
            elapsed = (now - last_sent).total_seconds()
            if elapsed < self._config.error_cooldown_seconds:
                print(f"skip duplicated error alert: {error_hash}")
                return

        message = "\n".join(
            [
                "Longbridge 量化监控异常",
                "",
                f"时间：{now.isoformat(timespec='seconds')}",
                f"标的：{self._config.symbol}",
                f"策略：EMA{self._config.fast}/EMA{self._config.slow}",
                "",
                "可能原因：",
                "- LONGBRIDGE_ACCESS_TOKEN 过期或无效",
                "- LONGBRIDGE_APP_KEY / LONGBRIDGE_APP_SECRET / LONGBRIDGE_ACCESS_TOKEN 缺失",
                "- 行情权限不足",
                "- 网络或 Longbridge OpenAPI 暂时不可用",
                "",
                f"错误：{error_text}",
            ]
        )
        try:
            FeishuNotifier.from_env().send_text(message)
            self._state.set(last_error_key, now.isoformat())
            print(f"sent error alert: {error_hash}")
        except Exception as notify_exc:
            print(f"failed to send error alert: {notify_exc}")


def _parse_run_at(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("run_at must be HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("run_at must be HH:MM")
    return hour, minute
