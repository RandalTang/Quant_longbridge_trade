"""实时信号端到端测试：真实行情 → 策略计算 → 飞书通知。

和线上 daemon 走完全相同的代码路径，只是手动触发一次：
create_broker() 连真实券商 → 拉日线 K 线 + 实时报价 → EMA5/EMA30 策略
→ 查真实持仓 → 拼消息 → 发飞书。

用法：

    python tests/test_live_signal.py            # 实时计算并发送到飞书
    python tests/test_live_signal.py --dry-run  # 只计算打印，不发飞书

前置条件：.env 配好长桥 API Key（LONGBRIDGE_APP_KEY / APP_SECRET / ACCESS_TOKEN）；
发飞书还需要 FEISHU_WEBHOOK_URL。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_longbridge_trade.brokers import create_broker  # noqa: E402
from quant_longbridge_trade.ema_service import (  # noqa: E402
    check_ema_preview_signal,
    check_ema_signal,
    check_sqqq_death_cross,
)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    now = datetime.now().isoformat(timespec="seconds")

    try:
        broker = create_broker()
    except Exception as exc:
        print(f"[失败] 创建券商实例出错：{exc}", file=sys.stderr)
        return 2

    print(f"券商：{broker.name}")
    print(f"时间：{now}")
    print("=" * 40)

    # 1. 收盘确认信号（用真实日线 K 线）
    try:
        confirmed = check_ema_signal(broker, symbol="TQQQ.US")
    except Exception as exc:
        print(f"[失败] 确认信号计算出错：{exc}", file=sys.stderr)
        print("常见原因：API Key 过期/无效、行情权限不足、网络不通。", file=sys.stderr)
        return 1
    print("\n--- TQQQ 收盘确认信号 ---")
    print(confirmed.message)

    # 2. 盘中预览信号（用实时价模拟今日收盘）
    try:
        preview = check_ema_preview_signal(broker, symbol="TQQQ.US")
    except Exception as exc:
        print(f"[失败] 预览信号计算出错：{exc}", file=sys.stderr)
        return 1
    print("\n--- TQQQ 盘中预览信号（实时价模拟收盘） ---")
    print(preview.message)

    # 3. SQQQ 死叉检查
    try:
        sqqq = check_sqqq_death_cross(broker, symbol="SQQQ.US")
    except Exception as exc:
        print(f"[失败] SQQQ 检查出错：{exc}", file=sys.stderr)
        return 1
    print("\n--- SQQQ 状态 ---")
    print(f"信号：{sqqq.signal.signal}（{sqqq.signal.reason}）")

    print("\n" + "=" * 40)
    print(
        f"实时计算结果：确认={confirmed.signal.signal} "
        f"预览={preview.signal.signal} SQQQ={sqqq.signal.signal}"
    )

    if dry_run:
        print("\n--dry-run：跳过飞书发送。")
        return 0

    # 4. 发送到飞书（无论有没有买卖信号都发，方便核对链路和格式）
    from quant_longbridge_trade.notifier import FeishuNotifier

    try:
        notifier = FeishuNotifier.from_env()
    except Exception as exc:
        print(f"[失败] 飞书配置出错：{exc}", file=sys.stderr)
        return 2

    header = f"【实时链路测试】{now} 手动触发，数据为真实行情"
    messages = [
        ("确认信号", f"{header}\n\n{confirmed.message}"),
        ("预览信号", f"{header}\n\n{preview.message}"),
    ]
    if sqqq.signal.signal in {"SELL", "SELL_PREVIEW"}:
        messages.append(("SQQQ 死叉", f"{header}\n\n{sqqq.message}"))

    failed = False
    for label, message in messages:
        try:
            notifier.send_text(message)
            print(f"[飞书] 已发送：{label}")
        except Exception as exc:
            failed = True
            print(f"[飞书] 发送失败（{label}）：{exc}", file=sys.stderr)

    if failed:
        return 1
    print("\n发送完成，去飞书群里核对消息内容是否和上面打印的一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
