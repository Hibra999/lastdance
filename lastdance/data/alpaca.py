from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from lastdance.data.normalize import normalize_ohlcv, validate_ohlcv

ALPACA_CRYPTO_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "1h": "1Hour",
    "4h": "4Hour",
    "1d": "1Day",
}


def equivalent_symbol(pair: str) -> str:
    base, quote = pair.split("/", 1)
    if quote != "USD":
        raise ValueError("Alpaca proxy mapping is restricted to USD-quoted symbols")
    return f"{base}/USD"


def fetch_crypto_bars(
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    session: requests.Session | None = None,
    cache_path: Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Fetch Alpaca crypto bars while preserving explicit non-Bitso provenance."""
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_API_SECRET", "")
    if bool(key) != bool(secret):
        raise RuntimeError("Set both ALPACA_API_KEY and ALPACA_API_SECRET, or neither")
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Unsupported Alpaca timeframe: {timeframe}")
    client = session or requests.Session()
    headers = (
        {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret} if key and secret else {}
    )
    params: dict[str, Any] = {
        "symbols": equivalent_symbol(pair),
        "timeframe": TIMEFRAME_MAP[timeframe],
        "start": start.astimezone(UTC).isoformat(),
        "end": end.astimezone(UTC).isoformat(),
        "limit": 10_000,
    }
    rows: list[list[Any]] = []
    page_count = 0
    while True:
        for attempt in range(3):
            response = client.get(ALPACA_CRYPTO_URL, headers=headers, params=params, timeout=30)
            if response.status_code != 429 and response.status_code < 500:
                break
            if attempt < 2:
                time.sleep(min(float(response.headers.get("Retry-After", 1)), 5.0))
        response.raise_for_status()
        page_count += 1
        payload = response.json()
        for bar in payload.get("bars", {}).get(equivalent_symbol(pair), []):
            rows.append([bar["t"], bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]])
        token = payload.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    frame = normalize_ohlcv(rows, timestamp_unit="ns") if rows and isinstance(rows[0][0], int) else _normalize_iso(rows)
    validation = validate_ohlcv(frame)
    provenance = {
        "data_source": "alpaca",
        "exchange_reference": "alpaca_crypto_us",
        "pair": pair,
        "provider_symbol": equivalent_symbol(pair),
        "timeframe": timeframe,
        "proxy_market_data": True,
        "first_candle": validation.first_candle,
        "last_candle": validation.last_candle,
        "rows": validation.rows,
        "pages": page_count,
        "valid": validation.valid,
    }
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_feather(cache_path)
    return frame, provenance


def _normalize_iso(rows: list[list[Any]]) -> Any:
    import pandas as pd

    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
