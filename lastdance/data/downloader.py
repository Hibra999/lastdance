from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from lastdance.data.alpaca import fetch_crypto_bars
from lastdance.data.normalize import (
    cache_file,
    inspect_cache_file,
    normalize_cache_file,
    timeframe_delta,
)
from lastdance.exchanges.freqtrade_config import freqtrade_environment
from lastdance.paths import PROJECT_ROOT, USER_DATA_DIR, resolve_project_path


def run_freqtrade(
    command: list[str], *, log_path: Path | None = None, timeout: int | None = None
) -> dict[str, Any]:
    full_command = [sys.executable, "-m", "freqtrade", *command]
    started = datetime.now(UTC)
    process = subprocess.run(
        full_command,
        cwd=PROJECT_ROOT,
        env=freqtrade_environment(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = f"{process.stdout}\n{process.stderr}".strip()
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output + "\n", encoding="utf-8")
    return {
        "command": command,
        "returncode": process.returncode,
        "runtime_seconds": (datetime.now(UTC) - started).total_seconds(),
        "output": output,
    }


def download_bitso_data(
    runtime_config: Path,
    pairs: list[str],
    timeframes: list[str],
    timerange: str,
    *,
    startup_candles: int = 800,
    log_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = USER_DATA_DIR / "data"
    started = datetime.now(UTC)
    commands: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    start_text, separator, end_text = timerange.partition("-")
    if not separator or len(start_text) != 8:
        raise ValueError(f"Unsupported timerange: {timerange}")
    backtest_start = pd.Timestamp(datetime.strptime(start_text, "%Y%m%d"), tz="UTC")

    def warm_start(timeframe: str) -> pd.Timestamp:
        return (backtest_start - (startup_candles + 2) * timeframe_delta(timeframe)).floor("D")

    def invoke(timeframe: str, selected_pairs: list[str], *, prepend: bool) -> bool:
        if not selected_pairs:
            return True
        expanded = f"{warm_start(timeframe):%Y%m%d}-{end_text}"
        command = [
            "download-data",
            "--config",
            str(runtime_config),
            "--datadir",
            str(data_dir),
            "--trading-mode",
            "spot",
            "--timerange",
            expanded,
            "--timeframes",
            timeframe,
            "--pairs",
            *selected_pairs,
        ]
        if prepend:
            command.append("--prepend")
        result: dict[str, Any] | None = None
        for _ in range(2):
            result = run_freqtrade(command)
            commands.append(result)
            if result["returncode"] == 0:
                break
        assert result is not None
        stages.append(
            {
                "timeframe": timeframe,
                "mode": "prepend" if prepend else "update",
                "pairs": selected_pairs,
                "returncode": result["returncode"],
            }
        )
        return result["returncode"] == 0

    for timeframe in timeframes:
        existing: list[str] = []
        missing: list[str] = []
        for pair in pairs:
            path = cache_file(data_dir, pair, timeframe)
            if path.is_file():
                normalized.append(normalize_cache_file(path, timeframe))
                first = pd.read_feather(path, columns=["date"])["date"].min()
                if pd.isna(first) or pd.Timestamp(first) > warm_start(timeframe):
                    existing.append(pair)
            else:
                missing.append(pair)
        prepared = invoke(timeframe, existing, prepend=True)
        prepared = invoke(timeframe, missing, prepend=False) and prepared
        if prepared:
            invoke(timeframe, pairs, prepend=False)
        for pair in pairs:
            path = cache_file(data_dir, pair, timeframe)
            if path.is_file():
                normalized.append(normalize_cache_file(path, timeframe))

    output = "\n\n".join(item["output"] for item in commands)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output + "\n", encoding="utf-8")
    return {
        "command_count": len(commands),
        "commands": [item["command"] for item in commands],
        "stages": stages,
        "returncode": max((item["returncode"] for item in stages), default=0),
        "runtime_seconds": (datetime.now(UTC) - started).total_seconds(),
        "normalization": normalized,
        "output_tail": output[-4000:],
    }


def configured_data_dir(app: dict[str, Any]) -> Path:
    return resolve_project_path(app["data"].get("cache_dir", USER_DATA_DIR / "data"))


def download_alpaca_data(
    pairs: list[str],
    timeframes: list[str],
    timerange: str,
    *,
    startup_candles: int = 800,
    data_dir: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Update a dedicated Alpaca cache without re-downloading covered history."""
    start_text, separator, _ = timerange.partition("-")
    if not separator or len(start_text) != 8:
        raise ValueError(f"Unsupported timerange: {timerange}")
    backtest_start = pd.Timestamp(datetime.strptime(start_text, "%Y%m%d"), tz="UTC")
    current = pd.Timestamp(now or datetime.now(UTC))
    started = datetime.now(UTC)
    files: list[dict[str, Any]] = []
    request_count = 0
    page_count = 0
    eligible_pairs = list(pairs)
    preflight_excluded_pairs: list[str] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    ordered_timeframes = sorted(timeframes, key=lambda item: item != "1d")
    for timeframe in ordered_timeframes:
        delta = timeframe_delta(timeframe)
        buffer_candles = max(2, startup_candles // 10)
        required_start = (backtest_start - (startup_candles + buffer_candles) * delta).floor(delta)
        closed_end = current.floor(delta) - delta
        selected_pairs = pairs if timeframe == "1d" else eligible_pairs
        for pair in selected_pairs:
            path = cache_file(data_dir, pair, timeframe)
            coverage_path = path.with_suffix(path.suffix + ".coverage.json")
            attempted_start: pd.Timestamp | None = None
            attempted_end: pd.Timestamp | None = None
            if coverage_path.is_file():
                coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
                attempted_start = pd.Timestamp(coverage["requested_start"])
                if coverage.get("requested_end"):
                    attempted_end = pd.Timestamp(coverage["requested_end"])
            existing = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            if path.is_file():
                existing = pd.read_feather(path)
                existing["date"] = pd.to_datetime(existing["date"], utc=True, errors="coerce")

            ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
            history_cache_hit = False
            if existing.empty:
                if (
                    attempted_start is not None
                    and attempted_start <= required_start
                    and attempted_end is not None
                ):
                    history_cache_hit = True
                    if attempted_end < closed_end:
                        ranges.append((max(attempted_end + delta, required_start), closed_end))
                else:
                    ranges.append((required_start, closed_end))
            else:
                first = existing["date"].min()
                last = existing["date"].max()
                if first > required_start and (
                    attempted_start is None or attempted_start > required_start
                ):
                    ranges.append((required_start, min(first - delta, closed_end)))
                else:
                    history_cache_hit = True
                if last < closed_end:
                    ranges.append((max(last + delta, required_start), closed_end))

            additions: list[pd.DataFrame] = []
            pages = 0
            for fetch_start, fetch_end in ranges:
                if fetch_start > fetch_end:
                    continue
                frame, provenance = fetch_crypto_bars(
                    pair,
                    timeframe,
                    fetch_start.to_pydatetime(),
                    fetch_end.to_pydatetime(),
                )
                request_count += 1
                pages += int(provenance["pages"])
                page_count += int(provenance["pages"])
                additions.append(frame.rename(columns={"timestamp": "date"}))

            combined = pd.concat([existing, *additions], ignore_index=True)
            combined["date"] = pd.to_datetime(combined["date"], utc=True, errors="coerce")
            combined = (
                combined.dropna(subset=["date"])
                .sort_values("date")
                .drop_duplicates("date", keep="last")
                .reset_index(drop=True)
            )
            combined.to_feather(path)
            coverage_path.write_text(
                json.dumps(
                    {
                        "requested_start": required_start.isoformat(),
                        "requested_end": closed_end.isoformat(),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            normalization = normalize_cache_file(path, timeframe)
            files.append(
                {
                    "data_source": "alpaca",
                    "exchange_reference": "alpaca_crypto_us",
                    "proxy_market_data": True,
                    "pair": pair,
                    "timeframe": timeframe,
                    "path": str(path),
                    "cache_hit": not ranges,
                    "history_cache_hit": history_cache_hit,
                    "fetches": len(ranges),
                    "pages": pages,
                    **normalization,
                }
            )

        if timeframe == "1d":
            eligible_pairs = [
                pair
                for pair in pairs
                if not inspect_cache_file(
                    cache_file(data_dir, pair, timeframe),
                    timeframe,
                    backtest_start=backtest_start,
                    startup_candles=startup_candles,
                )["issues"]
            ]
            preflight_excluded_pairs = [pair for pair in pairs if pair not in eligible_pairs]

    return {
        "data_source": "alpaca",
        "exchange_reference": "alpaca_crypto_us",
        "proxy_market_data": True,
        "cache_dir": str(data_dir),
        "request_count": request_count,
        "page_count": page_count,
        "preflight_eligible_pairs": eligible_pairs,
        "preflight_excluded_pairs": preflight_excluded_pairs,
        "files": files,
        "returncode": 0,
        "runtime_seconds": (datetime.now(UTC) - started).total_seconds(),
    }
