from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil

from lastdance.config import load_app_config
from lastdance.data.downloader import run_freqtrade
from lastdance.data.normalize import cache_file, inspect_cache_file
from lastdance.exchanges.freqtrade_config import build_runtime_config, write_runtime_config
from lastdance.paths import NFI_ROOT, PROJECT_ROOT, RESULTS_DIR, USER_DATA_DIR
from lastdance.strategies.registry import StrategyRegistry
from lastdance.utils.jsonio import write_json


def git_revision(path: Path = PROJECT_ROOT) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True, check=False
    )
    return process.stdout.strip() if process.returncode == 0 else "uncommitted"


def auto_workers(strategy_count: int) -> int:
    cpu_bound = max(1, (os.cpu_count() or 2) // 8)
    memory_bound = max(1, int(psutil.virtual_memory().available // (8 * 1024**3)))
    return max(1, min(strategy_count, cpu_bound, memory_bound, 4))


def run_one(
    strategy: str,
    runtime_config: Path,
    timerange: str,
    run_dir: Path,
) -> dict[str, Any]:
    strategy_dir = run_dir / strategy
    strategy_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{strategy}.log"
    command = [
        "backtesting",
        "--config",
        str(runtime_config),
        "--strategy-path",
        str(NFI_ROOT),
        "--strategy",
        strategy,
        "--datadir",
        str(USER_DATA_DIR / "data"),
        "--timerange",
        timerange,
        "--export",
        "trades",
        "--backtest-directory",
        str(strategy_dir),
        "--notes",
        f"LastDance {strategy}",
        "--cache",
        "none",
    ]
    result = run_freqtrade(command, log_path=log_path)
    candidates = sorted(
        strategy_dir.glob("backtest-result-*"), key=lambda item: item.stat().st_mtime, reverse=True
    )
    exports = [
        str(item)
        for item in candidates
        if item.suffix.lower() == ".zip"
        or (item.suffix.lower() == ".json" and not item.name.endswith(".meta.json"))
    ]
    status = "failed"
    if result["returncode"] == 0:
        try:
            trade_count = _export_trade_count(next(Path(item) for item in exports), strategy)
            status = "success" if trade_count else "no_trades"
        except (
            OSError,
            StopIteration,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            zipfile.BadZipFile,
        ) as exc:
            status = "invalid_result"
            result["output"] += f"\nInvalid export: {exc}"
    return {
        "strategy": strategy,
        "status": status,
        "returncode": result["returncode"],
        "runtime_seconds": result["runtime_seconds"],
        "exports": exports,
        "log": str(log_path),
        "error_tail": result["output"][-2000:] if status not in {"success", "no_trades"} else "",
    }


def _export_trade_count(path: Path, strategy: str) -> int:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith(".json") and "config" not in name and "meta" not in name
            ]
            if not names:
                raise ValueError("export contains no result JSON")
            payload = json.loads(archive.read(names[0]))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    result = payload.get("strategy", {}).get(strategy)
    if not isinstance(result, dict) or "trades" not in result:
        raise ValueError("export has no strategy result")
    return len(result["trades"])


def _timerange_start(timerange: str) -> datetime:
    start = timerange.partition("-")[0]
    if len(start) != 8:
        raise ValueError(f"Timerange must begin with YYYYMMDD: {timerange}")
    return datetime.strptime(start, "%Y%m%d").replace(tzinfo=UTC)


def _data_inventory(
    pairs: list[str], timeframes: list[str], *, backtest_start: datetime, startup_candles: int
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    data_dir = USER_DATA_DIR / "data"
    for pair in pairs:
        for timeframe in timeframes:
            path = cache_file(data_dir, pair, timeframe)
            item = {
                "data_source": "bitso",
                "exchange_reference": "bitso",
                "proxy_market_data": False,
                "pair": pair,
                **inspect_cache_file(
                    path,
                    timeframe,
                    backtest_start=backtest_start,
                    startup_candles=startup_candles,
                ),
            }
            inventory.append(item)
    return inventory


def run_backtests(
    pairs: list[str],
    *,
    timerange: str,
    strategy_names: list[str] | None = None,
    workers: int | None = None,
    run_id: str | None = None,
    pair_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    app = load_app_config()
    registry = StrategyRegistry(app["strategies"]["registry"])
    strategies = strategy_names or [item.name for item in registry.enabled()]
    specs = [registry.get(name) for name in strategies]
    startup_candles = max((item.startup_candles for item in specs), default=0)
    timeframes = list(app["data"]["timeframes"])
    inventory = _data_inventory(
        pairs,
        timeframes,
        backtest_start=_timerange_start(timerange),
        startup_candles=startup_candles,
    )
    pair_issues = {
        pair: sorted(
            {
                f"{item['timeframe']}:{issue}"
                for item in inventory
                if item["pair"] == pair
                for issue in item["issues"]
            }
        )
        for pair in pairs
    }
    pairs_used = [pair for pair in pairs if not pair_issues[pair]]
    pairs_excluded = [
        {"pair": pair, "reasons": reasons} for pair, reasons in pair_issues.items() if reasons
    ]
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime_config = write_runtime_config(
        run_dir / "freqtrade.runtime.json",
        build_runtime_config(pairs_used or pairs, strategy=strategies[0] if strategies else None),
    )
    selected_workers = workers or auto_workers(len(strategies))
    outcomes: list[dict[str, Any]] = []
    if not pairs_used:
        outcomes = [
            {
                "strategy": strategy,
                "status": "invalid_data",
                "returncode": None,
                "runtime_seconds": 0.0,
                "exports": [],
                "log": None,
                "error_tail": "No pair passed the OHLCV integrity and startup-candle gate.",
            }
            for strategy in strategies
        ]
    else:
        with ThreadPoolExecutor(
            max_workers=selected_workers, thread_name_prefix="lastdance-backtest"
        ) as executor:
            futures = {
                executor.submit(run_one, strategy, runtime_config, timerange, run_dir): strategy
                for strategy in strategies
            }
            for future in as_completed(futures):
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    outcomes.append(
                        {
                            "strategy": futures[future],
                            "status": "failed",
                            "error_tail": f"{exc.__class__.__name__}: {exc}",
                        }
                    )
    packages = {}
    for package in ("freqtrade", "ccxt", "quantstats", "TA-Lib"):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = None
    metadata_payload = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "lastdance_git_commit": git_revision(),
        "nfi_commit": git_revision(NFI_ROOT),
        "packages": packages,
        "python": sys.version,
        "os": platform.platform(),
        "data_source": app["data"]["source"],
        "exchange_reference": app["exchange"]["name"],
        "proxy_market_data": bool(app["data"].get("proxy_market_data", False)),
        "timerange": timerange,
        "timeframes": timeframes,
        "startup_candles_required": startup_candles,
        "data_inventory": inventory,
        "pairs_requested": pairs,
        "pairs": pairs_used,
        "pairs_excluded": pairs_excluded,
        "pair_snapshot": pair_snapshot,
        "strategies": strategies,
        "acceleration_mode": app["acceleration"]["mode"],
        "cpu_workers": selected_workers,
        "outcomes": sorted(outcomes, key=lambda item: item["strategy"]),
    }
    write_json(run_dir / "metadata.json", metadata_payload)
    return metadata_payload
