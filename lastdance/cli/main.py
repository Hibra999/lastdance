from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from lastdance.acceleration.backend import benchmark_dict
from lastdance.backtesting.runner import run_backtests
from lastdance.config import load_app_config
from lastdance.data.downloader import (
    configured_data_dir,
    download_alpaca_data,
    download_bitso_data,
    run_freqtrade,
)
from lastdance.doctor import run_doctor
from lastdance.exchanges.bitso import discover_usd_universe, verify_account_read_only
from lastdance.exchanges.freqtrade_config import build_runtime_config, write_runtime_config
from lastdance.paths import NFI_ROOT, PROJECT_ROOT, RESULTS_DIR
from lastdance.reporting.consolidated import generate_report, latest_run_dir
from lastdance.strategies.compatibility import inspect_registry
from lastdance.strategies.registry import StrategyRegistry
from lastdance.strategies.runtime_patch import prepare_strategy_path
from lastdance.utils.jsonio import read_json, write_json


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _snapshot_path() -> Path:
    return RESULTS_DIR / "pairs" / "latest.json"


def _save_snapshot(snapshot: dict[str, Any]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(RESULTS_DIR / "pairs" / f"bitso-usd-{timestamp}.json", snapshot)
    return write_json(_snapshot_path(), snapshot)


def _load_or_discover_pairs(validate_history: bool = False) -> tuple[list[str], dict[str, Any]]:
    if _snapshot_path().exists() and not validate_history:
        snapshot = read_json(_snapshot_path())
    else:
        app = load_app_config()
        snapshot = discover_usd_universe(
            app["pairs"]["manual_exclusions"],
            quote=app["exchange"]["quote_currency"],
            validate_history=validate_history,
            min_history_days=int(app["pairs"].get("min_history_days", 14)),
        )
        _save_snapshot(snapshot)
    return list(snapshot["pairs_used"]), snapshot


def _timerange(days: int | None = None) -> str:
    if days:
        start = datetime.now(UTC) - timedelta(days=days)
        return f"{start:%Y%m%d}-"
    app = load_app_config()
    return f"{app['data']['history_start'].replace('-', '')}-"


def _data_pairs(app: dict[str, Any], discovered: list[str]) -> list[str]:
    return list(app["data"].get("pairs", discovered))


def _download_data(
    app: dict[str, Any], pairs: list[str], timeframes: list[str], timerange: str, startup_candles: int
) -> dict[str, Any]:
    if app["data"]["source"] == "alpaca":
        return download_alpaca_data(
            pairs,
            timeframes,
            timerange,
            startup_candles=startup_candles,
            data_dir=configured_data_dir(app),
        )
    runtime = write_runtime_config(RESULTS_DIR / "runtime" / "download.json", build_runtime_config(pairs))
    return download_bitso_data(
        runtime,
        pairs,
        timeframes,
        timerange,
        startup_candles=startup_candles,
        log_path=RESULTS_DIR / "runtime" / "download.log",
    )


def command_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(network=not args.no_network)
    _print(report)
    return 0 if report["healthy"] else 1


def command_pairs(args: argparse.Namespace) -> int:
    app = load_app_config()
    snapshot = discover_usd_universe(
        app["pairs"]["manual_exclusions"],
        quote=app["exchange"]["quote_currency"],
        validate_history=args.validate_history,
        min_history_days=args.min_history_days or int(app["pairs"].get("min_history_days", 14)),
    )
    path = _save_snapshot(snapshot)
    snapshot["snapshot_path"] = str(path)
    _print(snapshot)
    return 0 if snapshot["pairs_used"] else 1


def command_strategies(args: argparse.Namespace) -> int:
    registry = StrategyRegistry()
    payload: dict[str, Any] = {
        "upstream": registry.upstream,
        "enabled": [item.name for item in registry.enabled()],
        "strategies": inspect_registry(registry),
    }
    if args.freqtrade:
        pairs, _ = _load_or_discover_pairs()
        runtime = write_runtime_config(
            RESULTS_DIR / "runtime" / "strategy-check.json", build_runtime_config(pairs[:1] or ["BTC/USD"])
        )
        check = run_freqtrade(
            [
                "list-strategies",
                "--config",
                str(runtime),
                "--strategy-path",
                str(NFI_ROOT),
                "--no-color",
            ],
            log_path=RESULTS_DIR / "runtime" / "strategy-check.log",
        )
        payload["freqtrade_returncode"] = check["returncode"]
        payload["freqtrade_output"] = check["output"]
    _print(payload)
    return 0 if all(item.get("syntax_valid") for item in payload["strategies"]) else 1


def command_data(args: argparse.Namespace) -> int:
    app = load_app_config()
    startup_candles = max(
        (item.startup_candles for item in StrategyRegistry().enabled()), default=0
    )
    pairs, snapshot = _load_or_discover_pairs(validate_history=args.validate_history)
    pairs = args.pairs or _data_pairs(app, pairs)
    result = _download_data(
        app,
        pairs,
        args.timeframes or list(app["data"]["timeframes"]),
        _timerange(args.days),
        startup_candles,
    )
    result["pairs"] = pairs
    result["snapshot_generated_at"] = snapshot.get("generated_at")
    _print(result)
    return result["returncode"]


def command_backtest(args: argparse.Namespace) -> int:
    app = load_app_config()
    pairs, snapshot = _load_or_discover_pairs()
    pairs = args.pairs or _data_pairs(app, pairs)
    result = run_backtests(
        pairs,
        timerange=args.timerange or _timerange(args.days),
        strategy_names=args.strategies,
        workers=args.workers,
        pair_snapshot=snapshot,
    )
    _print(result)
    return 0 if any(item["status"] in {"success", "no_trades"} for item in result["outcomes"]) else 1


def command_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    output = generate_report(run_dir)
    print(output)
    if args.open:
        webbrowser.open(output.as_uri())
    return 0


def command_verify_bitso(args: argparse.Namespace) -> int:
    report = verify_account_read_only()
    _print(report)
    print("NO REAL ORDERS WERE PLACED")
    return 0 if report.get("api_reachable") else 1


def command_benchmark(args: argparse.Namespace) -> int:
    app = load_app_config()
    result = benchmark_dict(
        mode=args.mode or app["acceleration"]["mode"],
        elements=args.elements,
        rtol=float(app["acceleration"]["numeric_rtol"]),
        atol=float(app["acceleration"]["numeric_atol"]),
    )
    path = write_json(RESULTS_DIR / "benchmarks" / "latest.json", result)
    result["path"] = str(path)
    _print(result)
    return 0 if result["equivalent_cpu"] and result["equivalent_gpu"] is not False else 1


def command_all(args: argparse.Namespace) -> int:
    app = load_app_config()
    snapshot = discover_usd_universe(
        app["pairs"]["manual_exclusions"],
        quote=app["exchange"]["quote_currency"],
        validate_history=not args.smoke,
        min_history_days=int(app["pairs"]["min_history_days"]),
    )
    _save_snapshot(snapshot)
    pairs = _data_pairs(app, snapshot["pairs_used"])
    strategies = None
    days = None
    if args.smoke:
        pairs = ["BTC/USD"]
        strategies = ["NostalgiaForInfinityX7"]
        days = args.days or 45
    benchmark_result = benchmark_dict(mode=app["acceleration"]["mode"], elements=args.elements)
    write_json(RESULTS_DIR / "benchmarks" / "latest.json", benchmark_result)
    download = _download_data(
        app,
        pairs,
        list(app["data"]["timeframes"]),
        _timerange(days),
        max((item.startup_candles for item in StrategyRegistry().enabled()), default=0),
    )
    if download["returncode"]:
        _print({"stage": "download", **download})
        return download["returncode"]
    run = run_backtests(
        pairs,
        timerange=_timerange(days),
        strategy_names=strategies,
        pair_snapshot=snapshot,
    )
    run_dir = RESULTS_DIR / run["run_id"]
    report = generate_report(run_dir)
    summary = {
        "pairs": snapshot,
        "benchmark": benchmark_result,
        "download": download,
        "run": run,
        "report": str(report),
    }
    _print(summary)
    if args.open:
        webbrowser.open(report.as_uri())
    return 0 if any(item["status"] in {"success", "no_trades"} for item in run["outcomes"]) else 1


def command_dry_run(args: argparse.Namespace) -> int:
    pairs, _ = _load_or_discover_pairs()
    strategy = args.strategy or StrategyRegistry().enabled()[0].name
    spec = StrategyRegistry().get(strategy)
    strategy_path = prepare_strategy_path(spec.name, spec.source)
    runtime = write_runtime_config(
        RESULTS_DIR / "runtime" / "dry-run.json", build_runtime_config(pairs, strategy=strategy, dry_run=True)
    )
    if not args.start:
        _print(
            {"status": "ready", "dry_run": True, "strategy": strategy, "pairs": pairs, "config": str(runtime)}
        )
        return 0
    result = run_freqtrade(
        [
            "trade",
            "--config",
            str(runtime),
            "--strategy-path",
            str(strategy_path),
            "--strategy",
            strategy,
        ],
        log_path=PROJECT_ROOT / "logs" / "dry-run.log",
    )
    return result["returncode"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lastdance", description="Bitso/NFI research orchestration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Inspect the local environment")
    doctor.add_argument("--no-network", action="store_true")
    doctor.set_defaults(handler=command_doctor)
    pairs = subparsers.add_parser("pairs", help="Build a reproducible Bitso/USD universe snapshot")
    pairs.add_argument("--validate-history", action="store_true")
    pairs.add_argument("--min-history-days", type=int)
    pairs.set_defaults(handler=command_pairs)
    strategies = subparsers.add_parser("strategies", help="Inspect the NFI strategy registry")
    strategies.add_argument("--freqtrade", action="store_true", help="Also load strategies through Freqtrade")
    strategies.set_defaults(handler=command_strategies)
    data = subparsers.add_parser("data", help="Download/update Bitso candles through Freqtrade")
    data.add_argument("--days", type=int)
    data.add_argument("--pairs", nargs="+")
    data.add_argument("--timeframes", nargs="+")
    data.add_argument("--validate-history", action="store_true")
    data.set_defaults(handler=command_data)
    backtest = subparsers.add_parser("backtest", help="Run all enabled strategy backtests")
    backtest.add_argument("--days", type=int)
    backtest.add_argument("--timerange")
    backtest.add_argument("--pairs", nargs="+")
    backtest.add_argument("--strategies", nargs="+")
    backtest.add_argument("--workers", type=int)
    backtest.set_defaults(handler=command_backtest)
    report = subparsers.add_parser("report", help="Generate one consolidated HTML report")
    report.add_argument("--run-dir")
    report.add_argument("--open", action="store_true")
    report.set_defaults(handler=command_report)
    verify = subparsers.add_parser("verify-bitso", help="Read-only Bitso account verification")
    verify.set_defaults(handler=command_verify_bitso)
    benchmark = subparsers.add_parser("benchmark", help="Benchmark and validate CPU/GPU acceleration")
    benchmark.add_argument("--mode", choices=("auto", "cpu", "gpu"))
    benchmark.add_argument("--elements", type=int, default=1_000_000)
    benchmark.set_defaults(handler=command_benchmark)
    all_command = subparsers.add_parser("all", help="Run discovery, data, backtests and consolidated report")
    all_command.add_argument("--smoke", action="store_true", help="Use BTC/USD, X7, and a short range")
    all_command.add_argument("--days", type=int)
    all_command.add_argument("--elements", type=int, default=1_000_000)
    all_command.add_argument("--open", action="store_true")
    all_command.set_defaults(handler=command_all)
    dry = subparsers.add_parser("dry-run", help="Prepare or start a Freqtrade dry-run")
    dry.add_argument("--strategy")
    dry.add_argument("--start", action="store_true")
    dry.set_defaults(handler=command_dry_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
