from __future__ import annotations

import os


REQUIRED_API_KEY_ENV = (
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
)


def missing_api_key_env() -> list[str]:
    return [name for name in REQUIRED_API_KEY_ENV if not os.getenv(name)]


def create_trade_context():
    missing = missing_api_key_env()
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Longbridge API key environment is incomplete. "
            f"Missing: {joined}. See .env.example for the expected variables."
        )

    try:
        from longbridge.openapi import Config, TradeContext
    except ImportError as exc:
        raise RuntimeError(
            "The longbridge SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    config = Config.from_apikey_env()
    return TradeContext(config)
