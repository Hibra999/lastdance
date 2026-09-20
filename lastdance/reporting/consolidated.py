from __future__ import annotations

import base64
import io
import json
import math
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd
import quantstats as qs
from jinja2 import Template

from lastdance.paths import REPORTS_DIR, RESULTS_DIR
from lastdance.utils.jsonio import read_json

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


def _read_export(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".json") and "config" not in name]
            if not names:
                return {}
            return json.loads(archive.read(names[0]).decode("utf-8"))
    return read_json(path)


def _trades_from_export(payload: dict[str, Any], strategy: str) -> list[dict[str, Any]]:
    if "strategy" in payload and isinstance(payload["strategy"], dict):
        return list(payload["strategy"].get(strategy, {}).get("trades", []))
    if "trades" in payload:
        return list(payload["trades"])
    return []


def _daily_returns(trades: list[dict[str, Any]]) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(trades)
    date_column = "close_date" if "close_date" in frame else "close_date_utc"
    frame[date_column] = pd.to_datetime(frame[date_column], utc=True, errors="coerce")
    frame["profit_ratio"] = pd.to_numeric(frame["profit_ratio"], errors="coerce").fillna(0.0)
    series = frame.dropna(subset=[date_column]).set_index(date_column)["profit_ratio"]
    daily = series.resample("1D").apply(lambda values: (1.0 + values).prod() - 1.0)
    return daily.asfreq("1D", fill_value=0.0)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metrics(trades: list[dict[str, Any]]) -> tuple[dict[str, Any], pd.Series]:
    returns = _daily_returns(trades)
    profits = [float(item.get("profit_ratio", 0.0)) for item in trades]
    positive = sum(value for value in profits if value > 0)
    negative = abs(sum(value for value in profits if value < 0))
    durations = [float(item.get("trade_duration", 0.0) or 0.0) for item in trades]
    period_minutes = 0.0
    if not returns.empty:
        period_minutes = max((returns.index.max() - returns.index.min()).total_seconds() / 60.0, 1.0)
    metric = {
        "trades": len(trades),
        "return_total": _finite(qs.stats.comp(returns)) if not returns.empty else 0.0,
        "cagr": _finite(qs.stats.cagr(returns)) if len(returns) > 365 else None,
        "sharpe": _finite(qs.stats.sharpe(returns)) if not returns.empty else None,
        "sortino": _finite(qs.stats.sortino(returns)) if not returns.empty else None,
        "calmar": _finite(qs.stats.calmar(returns)) if not returns.empty else None,
        "max_drawdown": _finite(qs.stats.max_drawdown(returns)) if not returns.empty else None,
        "volatility": _finite(qs.stats.volatility(returns)) if not returns.empty else None,
        "win_rate": sum(value > 0 for value in profits) / len(profits) if profits else 0.0,
        "profit_factor": positive / negative if negative else (None if not positive else float("inf")),
        "average_trade": sum(profits) / len(profits) if profits else 0.0,
        "best_trade": max(profits) if profits else None,
        "worst_trade": min(profits) if profits else None,
        "average_duration_minutes": sum(durations) / len(durations) if durations else 0.0,
        "exposure": min(sum(durations) / period_minutes, 1.0) if period_minutes else 0.0,
        "backtest_duration_days": period_minutes / 1440.0,
        "pairs": sorted({str(item.get("pair")) for item in trades if item.get("pair")}),
        "first_close": returns.index.min().isoformat() if not returns.empty else None,
        "last_close": returns.index.max().isoformat() if not returns.empty else None,
    }
    return metric, returns


def _chart(returns: pd.Series, title: str) -> str | None:
    if returns.empty:
        return None
    cumulative = (1.0 + returns).cumprod() - 1.0
    fig, axis = plt.subplots(figsize=(9, 2.8), dpi=120)
    cumulative.plot(ax=axis, color="#21c7a8", linewidth=1.6)
    axis.set_title(title)
    axis.set_ylabel("Cumulative return")
    axis.grid(alpha=0.2)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


REPORT_TEMPLATE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LastDance consolidated report</title><style>
body{font-family:Segoe UI,Arial,sans-serif;background:#0f1720;color:#e8eef5;margin:0}main{max-width:1180px;margin:auto;padding:32px}
h1,h2{color:#fff} .muted{color:#9fb0c3}.card{background:#172331;border:1px solid #2a3c50;border-radius:10px;padding:18px;margin:16px 0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:9px;border-bottom:1px solid #2a3c50;text-align:right}th:first-child,td:first-child{text-align:left}
.ok{color:#45d49a}.fail{color:#ff7b7b}img{max-width:100%;background:white;border-radius:6px}.pill{background:#23364a;padding:3px 8px;border-radius:12px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b121a;padding:12px;border-radius:6px}</style></head><body><main>
<h1>LastDance — consolidated backtest</h1><p class="muted">Generated {{ generated }} · Bitso spot · USD · {{ metadata.timerange }} · source={{ metadata.data_source }}</p>
<div class="card"><h2>Global comparison</h2><table><thead><tr><th>Strategy</th><th>Status</th><th>Trades</th><th>Total return</th><th>Sharpe</th><th>Sortino</th><th>Max DD</th><th>Win rate</th><th>Runtime</th></tr></thead><tbody>
{% for row in rows %}<tr><td>{{ row.strategy }}</td><td class="{{ 'ok' if row.status == 'success' else 'fail' }}">{{ row.status }}</td><td>{{ row.metrics.trades if row.metrics else '—' }}</td><td>{{ fmt_pct(row.metrics.return_total) if row.metrics else '—' }}</td><td>{{ fmt_num(row.metrics.sharpe) if row.metrics else '—' }}</td><td>{{ fmt_num(row.metrics.sortino) if row.metrics else '—' }}</td><td>{{ fmt_pct(row.metrics.max_drawdown) if row.metrics else '—' }}</td><td>{{ fmt_pct(row.metrics.win_rate) if row.metrics else '—' }}</td><td>{{ fmt_num(row.runtime_seconds) }}s</td></tr>{% endfor %}
</tbody></table></div>
{% for row in rows %}<section class="card"><h2>{{ row.strategy }} <span class="pill {{ 'ok' if row.status == 'success' else 'fail' }}">{{ row.status }}</span></h2>
{% if row.metrics %}<p>Trades: {{ row.metrics.trades }} · Average: {{ fmt_pct(row.metrics.average_trade) }} · Best: {{ fmt_pct(row.metrics.best_trade) }} · Worst: {{ fmt_pct(row.metrics.worst_trade) }} · Profit factor: {{ fmt_num(row.metrics.profit_factor) }}</p>
<p>CAGR: {{ fmt_pct(row.metrics.cagr) }} · Sharpe: {{ fmt_num(row.metrics.sharpe) }} · Sortino: {{ fmt_num(row.metrics.sortino) }} · Calmar: {{ fmt_num(row.metrics.calmar) }} · Volatility: {{ fmt_pct(row.metrics.volatility) }} · Max drawdown: {{ fmt_pct(row.metrics.max_drawdown) }}</p>
<p>Win rate: {{ fmt_pct(row.metrics.win_rate) }} · Exposure: {{ fmt_pct(row.metrics.exposure) }} · Backtest duration: {{ fmt_num(row.metrics.backtest_duration_days) }} days · Average trade duration: {{ fmt_num(row.metrics.average_duration_minutes) }} minutes</p>
<p class="muted">Pairs: {{ row.metrics.pairs|join(', ') if row.metrics.pairs else 'none' }} · {{ row.metrics.first_close }} — {{ row.metrics.last_close }}</p>{% if row.chart %}<img src="data:image/png;base64,{{ row.chart }}" alt="{{ row.strategy }} equity curve">{% endif %}
{% else %}<pre>{{ row.error }}</pre>{% endif %}</section>{% endfor %}
<div class="card"><h2>Reproducibility metadata</h2><pre>{{ metadata_json }}</pre></div>
<p class="muted">Research only. Backtests do not guarantee future results. Alpaca proxy data, when used, is explicitly marked and is never represented as Bitso execution data.</p>
</main></body></html>"""
)


def _fmt_num(value: Any) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number:.3f}"


def _fmt_pct(value: Any) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number * 100:.2f}%"


def generate_report(run_dir: Path, output: Path | None = None) -> Path:
    metadata = read_json(run_dir / "metadata.json")
    rows: list[dict[str, Any]] = []
    for outcome in metadata.get("outcomes", []):
        row = {**outcome, "metrics": None, "chart": None, "error": outcome.get("error_tail", "")}
        exports = [Path(value) for value in outcome.get("exports", [])]
        export = next((path for path in exports if path.exists()), None)
        if outcome.get("status") == "success" and export:
            payload = _read_export(export)
            trades = _trades_from_export(payload, outcome["strategy"])
            metrics, returns = _metrics(trades)
            row["metrics"] = metrics
            row["chart"] = _chart(returns, f"{outcome['strategy']} cumulative trade returns")
        rows.append(row)
    output = output or REPORTS_DIR / "latest" / "report.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        REPORT_TEMPLATE.render(
            generated=datetime.now(UTC).isoformat(),
            metadata=metadata,
            metadata_json=json.dumps(metadata, indent=2, sort_keys=True),
            rows=rows,
            fmt_num=_fmt_num,
            fmt_pct=_fmt_pct,
        ),
        encoding="utf-8",
    )
    return output


def latest_run_dir() -> Path:
    candidates = [
        path for path in RESULTS_DIR.iterdir() if path.is_dir() and (path / "metadata.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError("No completed LastDance run metadata was found")
    return max(candidates, key=lambda path: path.stat().st_mtime)
