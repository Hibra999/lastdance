from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lastdance.reporting import consolidated
from lastdance.reporting.consolidated import (
    _benchmark_returns,
    _monte_carlo,
    _portfolio_returns,
    _quantstats_report,
    generate_report,
)


def _result() -> dict[str, object]:
    return {
        "trades": [
            {
                "pair": "BTC/USD",
                "close_date": "2026-01-02T12:00:00Z",
                "profit_abs": 100.0,
                "profit_ratio": 0.02,
                "trade_duration": 60,
            },
            {
                "pair": "BTC/USD",
                "close_date": "2026-01-04T12:00:00Z",
                "profit_abs": -50.0,
                "profit_ratio": -0.01,
                "trade_duration": 120,
            },
        ],
        "starting_balance": 10_000.0,
        "final_balance": 10_050.0,
        "profit_total_abs": 50.0,
        "profit_mean": 0.005,
        "profit_factor": 2.0,
        "winrate": 0.5,
        "backtest_start": "2026-01-01 00:00:00",
        "backtest_end": "2026-01-05 00:00:00",
        "backtest_days": 4,
        "market_change": 0.03,
        "pairlist": ["BTC/USD"],
    }


def test_portfolio_returns_use_absolute_pnl_and_include_idle_days() -> None:
    returns, balances = _portfolio_returns(_result())
    assert len(returns) == 5
    assert returns.iloc[0] == 0.0
    assert returns.iloc[1] == 0.01
    assert returns.iloc[2] == 0.0
    assert returns.iloc[3] == -50 / 10_100
    assert balances["reconciliation_difference"] == 0.0


def test_portfolio_returns_prefer_freqtrade_mark_to_market_wallet() -> None:
    result = _result()
    wallet = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01T23:55:00Z", "2026-01-02T23:55:00Z", "2026-01-05T00:00:00Z"]
            ),
            "total_quote": [10_000.0, 9_900.0, 10_050.0],
        }
    )
    returns, balances = _portfolio_returns(result, wallet)
    assert returns.iloc[1] == pytest.approx(-0.01)
    assert returns.iloc[-1] == pytest.approx(10_050 / 9_900 - 1)
    assert balances["return_method"] == "freqtrade_wallet_mark_to_market"
    assert balances["reconciliation_difference"] == 0.0


def test_consolidated_report_generation(tmp_path: Path, monkeypatch) -> None:
    export = tmp_path / "Example.json"
    export.write_text(json.dumps({"strategy": {"Example": _result()}}), encoding="utf-8")
    metadata = {
        "timerange": "20260101-20260105",
        "data_source": "bitso",
        "pairs": ["BTC/USD"],
        "pairs_excluded": [],
        "startup_candles_required": 800,
        "data_inventory": [],
        "outcomes": [
            {"strategy": "Example", "status": "success", "runtime_seconds": 1.2, "exports": [str(export)]}
        ],
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(consolidated, "_quantstats_report", lambda *_: "<html>QuantStats native</html>")
    output = generate_report(tmp_path, tmp_path / "report.html")
    text = output.read_text(encoding="utf-8")
    assert "Comparación global" in text
    assert "Integridad de datos" in text
    assert "QuantStats · P&amp;L realizado vs Buy &amp; Hold" in text
    assert "QuantStats native" in text
    assert "$10,050.00" in text
    assert "Wins / Draws / Losses" in text
    assert "Monte Carlo" in text


def test_buy_hold_benchmark_is_named_and_held_to_end(tmp_path: Path) -> None:
    path = tmp_path / "BTC_USD-1d.feather"
    pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5, tz="UTC"),
            "close": [100.0, 105.0, 95.0, 110.0, 120.0],
        }
    ).to_feather(path)
    returns = pd.Series(0.0, index=pd.date_range("2026-01-01", periods=5))
    benchmark, pair = _benchmark_returns(
        {
            "data_inventory": [
                {
                    "pair": "BTC/USD",
                    "timeframe": "1d",
                    "quality_status": "valid",
                    "path": str(path),
                }
            ]
        },
        returns,
    )
    assert pair == "BTC/USD"
    assert benchmark is not None
    assert benchmark.name == "Buy & Hold BTC/USD"
    assert (1.0 + benchmark).prod() - 1.0 == pytest.approx(0.20)


def test_monte_carlo_is_reproducible() -> None:
    returns = pd.Series([0.01, 0.0, -0.005, 0.02])
    first = _monte_carlo(returns, simulations=500, seed=7, benchmark_return=0.01)
    second = _monte_carlo(returns, simulations=500, seed=7, benchmark_return=0.01)
    assert first == second
    assert first is not None
    assert 0 <= first["probability_profit"] <= 1
    assert first["return_p05"] <= first["return_p50"] <= first["return_p95"]


def test_quantstats_keeps_full_buy_hold_period(tmp_path: Path, monkeypatch) -> None:
    captured_html = {}
    captured_metrics = {}

    def fake_metrics(*_, **kwargs):
        captured_metrics.update(kwargs)

    def fake_report(*_, output, **kwargs) -> None:
        captured_html.update(kwargs)
        consolidated.qs.reports.metrics(returns=pd.Series(dtype=float))
        Path(output).write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setattr(consolidated.qs.reports, "metrics", fake_metrics)
    monkeypatch.setattr(consolidated.qs.reports, "html", fake_report)
    returns = pd.Series([0.0, 0.01], index=pd.date_range("2026-01-01", periods=2))
    benchmark = pd.Series([0.0, 0.02], index=returns.index)
    assert _quantstats_report(returns, benchmark, "Example", "Market", "Buy & Hold")
    assert captured_html["match_dates"] is False
    assert captured_metrics["match_dates"] is False


def test_metadata_json_is_not_accepted_as_a_zero_trade_result(tmp_path: Path) -> None:
    export = tmp_path / "backtest.meta.json"
    export.write_text(json.dumps({"notes": "not a result"}), encoding="utf-8")
    metadata = {
        "timerange": "20260101-20260105",
        "data_source": "bitso",
        "pairs": [],
        "data_inventory": [],
        "outcomes": [
            {"strategy": "Example", "status": "success", "runtime_seconds": 1.2, "exports": [str(export)]}
        ],
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    text = generate_report(tmp_path, tmp_path / "report.html").read_text(encoding="utf-8")
    assert "export inválido" in text
    assert "El archivo no contiene resultados" in text


def test_zero_trade_returns_cover_full_backtest_calendar() -> None:
    result = _result()
    result["trades"] = []
    result["final_balance"] = 10_000.0
    result["profit_total_abs"] = 0.0
    returns, _ = _portfolio_returns(result)
    assert returns.equals(pd.Series(0.0, index=pd.date_range("2026-01-01", "2026-01-05")))
