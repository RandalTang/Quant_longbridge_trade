"""飞书（Lark）webhook 连通性测试。

直接运行，往 .env 里配置的 FEISHU_WEBHOOK_URL 发一条测试消息：

    python tests/test_feishu_webhook.py

或者自定义消息内容：

    python tests/test_feishu_webhook.py "自定义测试内容"

前置条件：项目根目录 .env 里配好 FEISHU_WEBHOOK_URL，
如果机器人开了签名校验，还需要 FEISHU_WEBHOOK_SECRET。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 不依赖 pip install -e，直接把 src 加进 import 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_longbridge_trade.notifier import FeishuNotifier  # noqa: E402


def _masked_webhook_url() -> str:
    import os

    url = os.getenv("FEISHU_WEBHOOK_URL", "")
    if len(url) <= 12:
        return url or "(未配置)"
    return url[:40] + "..." + url[-6:]


def main() -> int:
    custom_text = sys.argv[1] if len(sys.argv) > 1 else None
    now = datetime.now().isoformat(timespec="seconds")
    text = custom_text or "\n".join(
        [
            "飞书 webhook 连通性测试",
            "",
            f"时间：{now}",
            "来源：tests/test_feishu_webhook.py",
            "",
            "如果你在群里看到这条消息，说明 webhook 配置正确。",
        ]
    )

    try:
        notifier = FeishuNotifier.from_env()
    except Exception as exc:
        print(f"[失败] 读取配置出错：{exc}", file=sys.stderr)
        print("请检查项目根目录 .env 里的 FEISHU_WEBHOOK_URL。", file=sys.stderr)
        return 2

    print(f"webhook：{_masked_webhook_url()}")
    print("正在发送测试消息...")

    try:
        notifier.send_text(text)
    except Exception as exc:
        print(f"[失败] 发送出错：{exc}", file=sys.stderr)
        print(
            "常见原因：webhook 地址失效、机器人被移出群、"
            "开了签名校验但 FEISHU_WEBHOOK_SECRET 没配或配错、网络不通。",
            file=sys.stderr,
        )
        return 1

    print("[成功] 已发送，去飞书群里确认是否收到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
