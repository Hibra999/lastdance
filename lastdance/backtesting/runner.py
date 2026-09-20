from __future__ import annotations

import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import pandas as pd
import psutil

from lastdance.config import load_app_config
from lastdance.data.downloader import run_freqtrade
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
    exports = [str(item) for item in candidates if item.suffix.lower() in {".json", ".zip"}]
    return {
        "strategy": strategy,
        "status": "success" if result["returncode"] == 0 else "failed",
        "returncode": result["returncode"],
        "runtime_seconds": result["runtime_seconds"],
        "exports": exports,
        "log": str(log_path),
        "error_tail": result["output"][-2000:] if result["returncode"] else "",
    }


def _data_inventory(pairs: list[str], timeframes: list[str]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    data_dir = USER_DATA_DIR / "data"
    for pair in pairs:
        stem = pair.replace("/", "_").replace(":", "_")
        for timeframe in timeframes:
            path = data_dir / f"{stem}-{timeframe}.feather"
            item: dict[str, Any] = {
                "data_source": "bitso",
                "exchange_reference": "bitso",
                "proxy_market_data": False,
                "pair": pair,
                "timeframe": timeframe,
                "path": str(path),
            }
            if path.is_file():
                frame = pd.read_feather(path, columns=["date"])
                item.update(
                    {
                        "candles": len(frame),
                        "first_candle": frame["date"].min().isoformat() if not frame.empty else None,
                        "last_candle": frame["date"].max().isoformat() if not frame.empty else None,
                    }
                )
            else:
                item.update({"candles": 0, "first_candle": None, "last_candle": None})
            inventory.append(item)
    return inventory


def run_backtests(
    pairs: list[str],
    *,
    timerange: str,
    strategy_names: list[str] | None = None,
    workers: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    app = load_app_config()
    registry = StrategyRegistry(app["strategies"]["registry"])
    strategies = strategy_names or [item.name for item in registry.enabled()]
    for name in strategies:
        registry.get(name)
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime_config = write_runtime_config(
        run_dir / "freqtrade.runtime.json",
        build_runtime_config(pairs, strategy=strategies[0] if strategies else None),
    )
    selected_workers = workers or auto_workers(len(strategies))
    outcomes: list[dict[str, Any]] = []
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
        "timeframes": app["data"]["timeframes"],
        "data_inventory": _data_inventory(pairs, list(app["data"]["timeframes"])),
        "pairs": pairs,
        "strategies": strategies,
        "acceleration_mode": app["acceleration"]["mode"],
        "cpu_workers": selected_workers,
        "outcomes": sorted(outcomes, key=lambda item: item["strategy"]),
    }
    write_json(run_dir / "metadata.json", metadata_payload)
    return metadata_payload
