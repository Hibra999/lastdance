from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import ccxt
from freqtrade.exchange import validate_exchange

from lastdance.config import load_yaml
from lastdance.paths import PROJECT_ROOT, resolve_project_path
from lastdance.utils.secrets import redact

CAPABILITY_KEYS = (
    "fetchMarkets",
    "fetchTicker",
    "fetchTickers",
    "fetchTrades",
    "fetchOHLCV",
    "fetchBalance",
    "fetchOrder",
    "fetchOpenOrders",
    "createOrder",
    "cancelOrder",
)


def create_exchange(*, authenticated: bool = False) -> ccxt.bitso:
    options: dict[str, Any] = {"enableRateLimit": True, "timeout": 30_000}
    if authenticated:
        options["apiKey"] = os.getenv("BITSO_API_KEY", "")
        options["secret"] = os.getenv("BITSO_API_SECRET", "")
    return ccxt.bitso(options)


def capability_report(exchange: ccxt.bitso | None = None) -> dict[str, Any]:
    client = exchange or create_exchange()
    return {
        "exchange": client.id,
        "ccxt_version": ccxt.__version__,
        "capabilities": {name: client.has.get(name, False) for name in CAPABILITY_KEYS},
        "timeframes": dict(client.timeframes or {}),
    }


def _time_synchronization(
    headers: dict[str, str], *, now: datetime | None = None
) -> dict[str, Any]:
    value = next((value for key, value in headers.items() if key.lower() == "date"), None)
    if not value:
        return {"checked": False, "reason": "Bitso HTTPS response did not include a Date header"}
    try:
        server_time = parsedate_to_datetime(value).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return {"checked": False, "reason": "Bitso HTTPS Date header was invalid"}
    local_time = now or datetime.now(UTC)
    offset = (server_time - local_time).total_seconds()
    return {
        "checked": True,
        "source": "Bitso HTTPS Date header",
        "server_time": server_time.isoformat(),
        "local_time": local_time.isoformat(),
        "offset_seconds": round(offset, 3),
        "within_30_seconds": abs(offset) <= 30,
    }


def freqtrade_compatibility_report() -> dict[str, Any]:
    valid, spot_limitations, futures_limitations, _ = validate_exchange("bitso")
    return {
        "version": metadata.version("freqtrade"),
        "exchange_valid": valid,
        "configured_mode": "spot",
        "spot_limitations": spot_limitations,
        "futures_limitations": futures_limitations,
    }


def _load_pair_rules(path: str | Path) -> tuple[dict[str, str], list[tuple[re.Pattern[str], str, str]]]:
    config = load_yaml(path)
    exact = {str(item["pair"]): str(item["reason"]) for item in config.get("manual_exclusions", [])}
    patterns: list[tuple[re.Pattern[str], str, str]] = []
    for item in config.get("blacklist_patterns", []):
        patterns.append((re.compile(item["pattern"], re.IGNORECASE), str(item["reason"]), "lastdance"))
    for raw_path in config.get("nfi_blacklist_sources", []):
        source = resolve_project_path(raw_path)
        if not source.is_file():
            continue
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for value in payload.get("exchange", {}).get("pair_blacklist", payload.get("pair_blacklist", [])):
            try:
                patterns.append(
                    (
                        re.compile(str(value), re.IGNORECASE),
                        f"NFI blacklist: {value}",
                        str(source.relative_to(PROJECT_ROOT)),
                    )
                )
            except re.error:
                continue
    return exact, patterns


def _history_is_sufficient(client: ccxt.bitso, pair: str, timeframe: str, days: int) -> tuple[bool, str]:
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        candles = client.fetch_ohlcv(pair, timeframe=timeframe, since=int(since.timestamp() * 1000), limit=2)
    except ccxt.BaseError as exc:
        return False, f"OHLCV error: {exc.__class__.__name__}"
    if not candles:
        return False, f"No {timeframe} candles in the last {days} days"
    return True, "history_available"


def discover_usd_universe(
    rules_path: str | Path = "config/pairs.yaml",
    *,
    quote: str = "USD",
    validate_history: bool = False,
    min_history_days: int = 14,
    timeframe: str = "5m",
) -> dict[str, Any]:
    client = create_exchange()
    markets = client.load_markets()
    exact, patterns = _load_pair_rules(rules_path)
    included: list[str] = []
    excluded: list[dict[str, str]] = []
    candidates = 0
    for symbol, market in sorted(markets.items()):
        reasons: list[str] = []
        if market.get("quote") != quote:
            continue
        candidates += 1
        if market.get("active") is False:
            reasons.append("inactive_market")
        if not market.get("spot"):
            reasons.append("not_spot")
        if not market.get("base") or not market.get("quote"):
            reasons.append("invalid_market_metadata")
        if symbol in exact:
            reasons.append(exact[symbol])
        for pattern, reason, source in patterns:
            if pattern.fullmatch(symbol) or pattern.match(symbol):
                reasons.append(f"{reason} [{source}]")
                break
        if not reasons and validate_history:
            valid, reason = _history_is_sufficient(client, symbol, timeframe, min_history_days)
            if not valid:
                reasons.append(reason)
        if reasons:
            excluded.append({"pair": symbol, "reason": "; ".join(dict.fromkeys(reasons))})
        else:
            included.append(symbol)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "exchange": "bitso",
        "quote": quote,
        "markets_total": len(markets),
        "quote_markets_found": candidates,
        "pairs_used": included,
        "pairs_excluded": excluded,
        "history_validated": validate_history,
        "min_history_days": min_history_days if validate_history else None,
        "capability_report": capability_report(client),
    }


def verify_account_read_only() -> dict[str, Any]:
    key = os.getenv("BITSO_API_KEY", "")
    secret = os.getenv("BITSO_API_SECRET", "")
    authenticated = bool(key and secret)
    client = create_exchange(authenticated=authenticated)
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "api_reachable": False,
        "credentials_present": authenticated,
        "credentials": {"key": redact(key), "secret": redact(secret)},
        "authenticated": False,
        "permissions": "not exposed by CCXT/Bitso",
        "orders_placed": 0,
        "safety_message": "NO REAL ORDERS WERE PLACED",
    }
    try:
        markets = client.load_markets()
        report["api_reachable"] = True
        report["markets"] = len(markets)
        report["time_synchronization"] = _time_synchronization(client.last_response_headers or {})
        report["freqtrade_integration"] = freqtrade_compatibility_report()
        report["usd_pairs"] = sorted(
            symbol
            for symbol, market in markets.items()
            if market.get("quote") == "USD" and market.get("spot")
        )
        report.update(capability_report(client))
        if authenticated:
            balances = client.fetch_balance()
            report["authenticated"] = True
            report["nonzero_balance_currencies"] = sorted(
                currency for currency, amount in balances.get("total", {}).items() if amount
            )
        else:
            report["authentication_status"] = "skipped: BITSO_API_KEY/BITSO_API_SECRET are not both set"
    except ccxt.AuthenticationError as exc:
        report["authentication_error"] = exc.__class__.__name__
    except ccxt.BaseError as exc:
        report["api_error"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
    return report
