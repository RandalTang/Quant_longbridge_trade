from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .config import load_local_env


@dataclass(frozen=True)
class FeishuConfig:
    webhook_url: str
    secret: Optional[str] = None


class FeishuNotifier:
    def __init__(self, config: FeishuConfig) -> None:
        self._config = config

    @classmethod
    def from_env(cls) -> "FeishuNotifier":
        load_local_env()
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
        if not webhook_url:
            raise RuntimeError("Missing FEISHU_WEBHOOK_URL. See .env.example.")
        return cls(FeishuConfig(webhook_url=webhook_url, secret=os.getenv("FEISHU_WEBHOOK_SECRET")))

    def send_text(self, text: str) -> None:
        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if self._config.secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = _feishu_sign(timestamp, self._config.secret)

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._config.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to send Feishu notification: {exc}") from exc

        code = body.get("code", body.get("StatusCode", 0))
        if code not in (0, "0"):
            raise RuntimeError(f"Feishu notification failed: {body}")


def _feishu_sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")
