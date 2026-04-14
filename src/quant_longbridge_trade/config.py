from __future__ import annotations

import os
from pathlib import Path


REQUIRED_API_KEY_ENV = (
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
)


def load_local_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def missing_api_key_env() -> list[str]:
    load_local_env()
    return [name for name in REQUIRED_API_KEY_ENV if not os.getenv(name)]


def create_config():
    missing = missing_api_key_env()
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Longbridge API key environment is incomplete. "
            f"Missing: {joined}. See .env.example for the expected variables."
        )

    try:
        from longbridge.openapi import Config
    except ImportError as exc:
        raise RuntimeError(
            "The longbridge SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    return Config.from_apikey_env()


def create_trade_context():
    try:
        from longbridge.openapi import TradeContext
    except ImportError as exc:
        raise RuntimeError(
            "The longbridge SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    return TradeContext(create_config())


def create_quote_context():
    try:
        from longbridge.openapi import QuoteContext
    except ImportError as exc:
        raise RuntimeError(
            "The longbridge SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    return QuoteContext(create_config())
