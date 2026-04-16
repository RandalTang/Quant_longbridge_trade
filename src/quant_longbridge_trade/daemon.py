from __future__ import annotations

import hashlib
import traceback
from dataclasses import dataclass
from datetime import datetime
from time import sleep
from zoneinfo import ZoneInfo

from .config import create_quote_context, create_trade_context
from .ema_service import (
    check_ema_preview_signal,
    check_ema_signal,
    check_sqqq_death_cross,
    format_secondary_signal_status,
)
from .notifier import FeishuNotifier
from .state import JsonStateStore


@dataclass(frozen=True)
class DaemonConfig:
    symbol: str = "TQQQ.US"
    sqqq_symbol: str = "SQQQ.US"
    fast: int = 5
    slow: int = 30
    run_at: str = "16:10"
    timezone: str = "America/New_York"
    preclose_at: str = "15:55"
    confirm_at: str = "16:10"
    enable_preclose_warning: bool = True
    poll_seconds: int = 60
    candle_count: int = 300
    adjust_type: str = "forward"
    notify_no_signal: bool = False
    watch_sqqq_death_cross: bool = False
    notify_errors: bool = True
    error_cooldown_seconds: int = 3600
    state_path: str = ".data/alert_state.json"


class SignalDaemon:
    def __init__(self, config: DaemonConfig) -> None:
        self._config = config
        self._state = JsonStateStore(config.state_path)

    def run_forever(self) -> None:
        print(
            f"daemon started: symbol={self._config.symbol} preclose_at={self._config.preclose_at} "
            f"confirm_at={self._config.confirm_at} timezone={self._config.timezone}"
        )
        while True:
            for stage in self._due_stages():
                try:
                    self.run_once(stage=stage)
                    self._mark_stage_checked(stage)
                except Exception as exc:
                    print(f"[{datetime.now().isoformat(timespec='seconds')}] daemon {stage} error: {exc}")
                    if self._config.notify_errors:
                        self._notify_error(exc, stage=stage)
            sleep(self._config.poll_seconds)

    def run_once(self, stage: str = "CONFIRMED") -> None:
        quote_context = create_quote_context()
        trade_context = create_trade_context()
        notifier = FeishuNotifier.from_env()

        checker = check_ema_preview_signal if stage == "PREVIEW" else check_ema_signal
        result = checker(
            quote_context=quote_context,
            trade_context=trade_context,
            symbol=self._config.symbol,
            fast=self._config.fast,
            slow=self._config.slow,
            candle_count=self._config.candle_count,
            adjust_type=self._config.adjust_type,
        )

        now = datetime.now(ZoneInfo(self._config.timezone)).isoformat(timespec="seconds")
        print(f"[{now}] {stage} {result.signal.symbol} {result.signal.trade_date} {result.signal.signal}: {result.signal.reason}")

        sqqq_result = None
        if self._config.watch_sqqq_death_cross:
            sqqq_result = check_sqqq_death_cross(
                quote_context=quote_context,
                trade_context=trade_context,
                symbol=self._config.sqqq_symbol,
                fast=self._config.fast,
                slow=self._config.slow,
                candle_count=self._config.candle_count,
                adjust_type=self._config.adjust_type,
                preview=stage == "PREVIEW",
            )
            now = datetime.now(ZoneInfo(self._config.timezone)).isoformat(timespec="seconds")
            print(f"[{now}] {stage} {sqqq_result.signal.symbol} {sqqq_result.signal.trade_date} {sqqq_result.signal.signal}: {sqqq_result.signal.reason}")

        notification_message = result.message
        if sqqq_result is not None:
            notification_message = "\n\n".join(
                [
                    result.message,
                    "---",
                    format_secondary_signal_status(sqqq_result, "SQQQ 补充状态"),
                ]
            )

        if result.signal.has_signal:
            if self._state.was_sent(result.signal.dedupe_key):
                print(f"skip duplicated alert: {result.signal.dedupe_key}")
            else:
                notifier.send_text(notification_message)
                self._state.mark_sent(result.signal.dedupe_key)
                print(f"sent alert: {result.signal.dedupe_key}")
        elif self._config.notify_no_signal:
            key = result.signal.dedupe_key
            if not self._state.was_sent(key):
                notifier.send_text(notification_message)
                self._state.mark_sent(key)
                print(f"sent heartbeat: {key}")

        if sqqq_result is not None:
            self._send_sqqq_death_cross(sqqq_result, notifier)

    def _send_sqqq_death_cross(self, result, notifier: FeishuNotifier) -> None:
        if result.signal.signal not in {"SELL", "SELL_PREVIEW"}:
            return
        key = f"{result.signal.dedupe_key}:SQQQ_DEATH"
        if self._state.was_sent(key):
            print(f"skip duplicated SQQQ death alert: {key}")
            return
        notifier.send_text(result.message)
        self._state.mark_sent(key)
        print(f"sent SQQQ death alert: {key}")

    def _due_stages(self) -> list[str]:
        now = datetime.now(ZoneInfo(self._config.timezone))
        if not _is_weekday(now):
            return []

        stages: list[str] = []
        if self._config.enable_preclose_warning:
            if self._time_reached(now, self._config.preclose_at) and not self._stage_checked(now, "PREVIEW"):
                stages.append("PREVIEW")
        if self._time_reached(now, self._config.confirm_at) and not self._stage_checked(now, "CONFIRMED"):
            stages.append("CONFIRMED")
        return stages

    def _mark_stage_checked(self, stage: str) -> None:
        now = datetime.now(ZoneInfo(self._config.timezone))
        self._state.set(f"last_daemon_check:{stage}", self._stage_key(now, stage))

    def _stage_checked(self, now: datetime, stage: str) -> bool:
        return self._state.get(f"last_daemon_check:{stage}") == self._stage_key(now, stage)

    def _stage_key(self, now: datetime, stage: str) -> str:
        return f"{self._config.symbol}:{now.date().isoformat()}:{stage}"

    def _time_reached(self, now: datetime, value: str) -> bool:
        hour, minute = _parse_run_at(value)
        return now.hour > hour or (now.hour == hour and now.minute >= minute)

    def _notify_error(self, exc: Exception, stage: str = "UNKNOWN") -> None:
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
                f"阶段：{stage}",
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


def _is_weekday(now: datetime) -> bool:
    return now.weekday() < 5
