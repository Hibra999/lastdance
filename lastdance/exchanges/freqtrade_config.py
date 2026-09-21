from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from lastdance.paths import DEFAULT_FREQTRADE_CONFIG
from lastdance.utils.jsonio import write_json


def load_base_config(path: Path = DEFAULT_FREQTRADE_CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_runtime_config(
    pairs: list[str],
    blacklist: list[str] | None = None,
    *,
    strategy: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    config = deepcopy(load_base_config())
    config["dry_run"] = bool(dry_run)
    config["exchange"]["pair_whitelist"] = list(pairs)
    config["exchange"]["pair_blacklist"] = list(blacklist or [])
    if strategy:
        config["strategy"] = strategy
    if not dry_run:
        gates = (
            os.getenv("LIVE_TRADING", "").lower() == "true",
            os.getenv("LASTDANCE_LIVE_ACK", "") == "I_UNDERSTAND_REAL_ORDERS",
        )
        if not all(gates):
            raise RuntimeError("Live trading is blocked: both explicit environment safety gates are required")
    return config


def write_runtime_config(path: Path, config: dict[str, Any]) -> Path:
    for field in ("key", "secret", "password", "uid"):
        if config.get("exchange", {}).get(field):
            raise ValueError("Runtime configuration must not contain exchange credentials")
    telegram = config.get("telegram", {})
    if telegram.get("token") or telegram.get("chat_id"):
        raise ValueError("Runtime configuration must not contain Telegram credentials")
    return write_json(path, config)


def freqtrade_environment() -> dict[str, str]:
    env = dict(os.environ)
    mappings = {
        "BITSO_API_KEY": "FREQTRADE__EXCHANGE__KEY",
        "BITSO_API_SECRET": "FREQTRADE__EXCHANGE__SECRET",
        "TELEGRAM_BOT_TOKEN": "FREQTRADE__TELEGRAM__TOKEN",
        "TELEGRAM_CHAT_ID": "FREQTRADE__TELEGRAM__CHAT_ID",
    }
    for source, target in mappings.items():
        if env.get(source):
            env[target] = env[source]
    if env.get("FREQTRADE__TELEGRAM__TOKEN") and env.get("FREQTRADE__TELEGRAM__CHAT_ID"):
        env.setdefault("FREQTRADE__TELEGRAM__ENABLED", "true")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("NUMEXPR_MAX_THREADS", "16")
    return env
