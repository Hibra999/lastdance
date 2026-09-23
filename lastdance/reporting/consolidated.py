from __future__ import annotations

import io
import json
import math
import tempfile
import warnings
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import quantstats as qs
from jinja2 import Environment

from lastdance.paths import REPORTS_DIR, RESULTS_DIR
from lastdance.utils.jsonio import read_json


def _read_export(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith(".json") and "config" not in name and "meta" not in name
            ]
            if not names:
                raise ValueError("El ZIP no contiene un resultado JSON de Freqtrade")
            payload = json.loads(archive.read(names[0]))
    else:
        payload = read_json(path)
    if not isinstance(payload.get("strategy"), dict):
        raise ValueError("El archivo no contiene resultados de estrategia de Freqtrade")
    return payload


def _strategy_result(payload: dict[str, Any], strategy: str) -> dict[str, Any]:
    result = payload["strategy"].get(strategy)
    if not isinstance(result, dict) or not isinstance(result.get("trades"), list):
        raise ValueError(f"El export no contiene el resultado de {strategy}")
    return result


def _read_wallet(path: Path) -> pd.DataFrame | None:
    if path.suffix.lower() != ".zip":
        return None
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith("_wallet.feather")]
        if not names:
            return None
        return pd.read_feather(io.BytesIO(archive.read(names[0])))


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _portfolio_returns(
    result: dict[str, Any], wallet: pd.DataFrame | None = None
) -> tuple[pd.Series, dict[str, Any]]:
    start_balance = _finite(result.get("starting_balance"))
    final_balance = _finite(result.get("final_balance"))
    if start_balance is None or start_balance <= 0:
        raise ValueError("Freqtrade no informó un starting_balance válido")
    start = _utc_timestamp(result["backtest_start"]).normalize()
    end = _utc_timestamp(result["backtest_end"]).normalize()
    if end < start:
        raise ValueError("El periodo del backtest es inválido")
    index = pd.date_range(start, end, freq="D", tz="UTC")
    wallet_final = None
    if wallet is not None and {"date", "total_quote"}.issubset(wallet.columns):
        wallet = wallet.copy()
        wallet["date"] = pd.to_datetime(wallet["date"], utc=True, errors="coerce")
        wallet["total_quote"] = pd.to_numeric(wallet["total_quote"], errors="coerce")
        if wallet[["date", "total_quote"]].isna().any().any():
            raise ValueError("La curva de wallet contiene fechas o valores inválidos")
        equity = wallet.groupby("date")["total_quote"].sum().sort_index()
        daily_equity = equity.resample("1D").last().reindex(index).ffill().fillna(start_balance)
        wallet_final = float(daily_equity.iloc[-1])
        if final_balance is not None:
            daily_equity.iloc[-1] = final_balance
        returns = daily_equity.div(daily_equity.shift(1, fill_value=start_balance)) - 1.0
        calculated_final = float(daily_equity.iloc[-1])
        return_method = "freqtrade_wallet_mark_to_market"
    else:
        daily_profit = pd.Series(0.0, index=index)
        trades = pd.DataFrame(result["trades"])
        if not trades.empty:
            date_column = "close_date" if "close_date" in trades else "close_date_utc"
            if date_column not in trades or "profit_abs" not in trades:
                raise ValueError("Las operaciones no incluyen close_date y profit_abs")
            trades[date_column] = pd.to_datetime(trades[date_column], utc=True, errors="coerce")
            trades["profit_abs"] = pd.to_numeric(trades["profit_abs"], errors="coerce")
            if trades[[date_column, "profit_abs"]].isna().any().any():
                raise ValueError("Las operaciones contienen fechas o ganancias absolutas inválidas")
            realized = trades.set_index(date_column)["profit_abs"].resample("1D").sum()
            realized.index = realized.index.normalize()
            daily_profit = daily_profit.add(realized, fill_value=0.0)
        prior_equity = start_balance + daily_profit.cumsum().shift(1, fill_value=0.0)
        returns = daily_profit.div(prior_equity.where(prior_equity != 0)).fillna(0.0)
        calculated_final = start_balance + float(daily_profit.sum())
        return_method = "realized_trade_pnl"
    returns.index = returns.index.tz_localize(None)
    reconciliation = None if final_balance is None else calculated_final - final_balance
    return returns, {
        "starting_balance": start_balance,
        "final_balance": final_balance,
        "calculated_final_balance": calculated_final,
        "reconciliation_difference": reconciliation,
        "wallet_final_before_reconciliation": wallet_final,
        "return_method": return_method,
    }


def _risk_metric(function: Any, returns: pd.Series, **kwargs: Any) -> float | None:
    if returns.empty or not returns.ne(0).any():
        return None
    return _finite(function(returns, **kwargs))


def _metrics(result: dict[str, Any], returns: pd.Series, balances: dict[str, Any]) -> dict[str, Any]:
    trades = result["trades"]
    profits = [_finite(item.get("profit_ratio")) or 0.0 for item in trades]
    absolute_profits = [_finite(item.get("profit_abs")) or 0.0 for item in trades]
    durations = [_finite(item.get("trade_duration")) or 0.0 for item in trades]
    winners = [value for value in profits if value > 0]
    losers = [value for value in profits if value < 0]
    draws = [value for value in profits if value == 0]
    gains = sum(value for value in absolute_profits if value > 0)
    losses = abs(sum(value for value in absolute_profits if value < 0))
    return {
        "trades": len(trades),
        "return_total": _finite(qs.stats.comp(returns)) if not returns.empty else None,
        "profit_total_abs": _finite(result.get("profit_total_abs")),
        "cagr": _risk_metric(qs.stats.cagr, returns, periods=365),
        "sharpe": _risk_metric(qs.stats.sharpe, returns, periods=365),
        "sortino": _risk_metric(qs.stats.sortino, returns, periods=365),
        "max_drawdown": _risk_metric(qs.stats.max_drawdown, returns),
        "volatility": _risk_metric(qs.stats.volatility, returns, periods=365),
        "wins": len(winners),
        "losses": len(losers),
        "draws": len(draws),
        "win_rate": len(winners) / len(trades) if trades else None,
        "profit_factor": gains / losses if losses else None,
        "average_trade": _finite(result.get("profit_mean")),
        "average_win": sum(winners) / len(winners) if winners else None,
        "average_loss": sum(losers) / len(losers) if losers else None,
        "best_trade": max(profits) if profits else None,
        "worst_trade": min(profits) if profits else None,
        "average_duration_minutes": sum(durations) / len(durations) if durations else None,
        "backtest_duration_days": _finite(result.get("backtest_days")),
        "trades_per_day": _finite(result.get("trades_per_day")),
        "winning_days": int(result.get("winning_days", 0)),
        "draw_days": int(result.get("draw_days", 0)),
        "losing_days": int(result.get("losing_days", 0)),
        "max_consecutive_wins": int(result.get("max_consecutive_wins", 0)),
        "max_consecutive_losses": int(result.get("max_consecutive_losses", 0)),
        "expectancy": _finite(result.get("expectancy")),
        "expectancy_ratio": _finite(result.get("expectancy_ratio")),
        "calmar": _finite(result.get("calmar")),
        "sqn": _finite(result.get("sqn")),
        "total_volume": _finite(result.get("total_volume")),
        "max_drawdown_abs": _finite(result.get("max_drawdown_abs")),
        "market_change": _finite(result.get("market_change")),
        "pairs": list(result.get("pairlist", [])),
        "backtest_start": result.get("backtest_start"),
        "backtest_end": result.get("backtest_end"),
        **balances,
    }


def _benchmark_returns(
    metadata: dict[str, Any], returns: pd.Series
) -> tuple[pd.Series | None, str | None]:
    candidates = sorted(
        metadata.get("data_inventory", []),
        key=lambda item: (item.get("pair") != "BTC/USD", item.get("timeframe") != "1d"),
    )
    item = next(
        (
            value
            for value in candidates
            if value.get("timeframe") == "1d"
            and value.get("quality_status") == "valid"
            and Path(str(value.get("path", ""))).is_file()
        ),
        None,
    )
    if item is None or returns.empty:
        return None, None
    frame = pd.read_feather(item["path"], columns=["date", "close"])
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None).dt.normalize()
    close = frame.drop_duplicates("date", keep="last").set_index("date")["close"].sort_index()
    close = close.reindex(returns.index).ffill()
    if close.isna().any():
        return None, None
    benchmark = close.pct_change(fill_method=None).fillna(0.0)
    pair = str(item["pair"])
    benchmark.name = f"Buy & Hold {pair}"
    return (benchmark, pair) if benchmark.notna().any() else (None, None)


def _buy_hold_metrics(
    benchmark: pd.Series | None, pair: str | None, starting_balance: float | None
) -> dict[str, Any]:
    total_return = None if benchmark is None else _finite(qs.stats.comp(benchmark))
    profit = (
        None
        if total_return is None or starting_balance is None
        else starting_balance * total_return
    )
    return {
        "buy_hold_pair": pair,
        "buy_hold_return": total_return,
        "buy_hold_profit_abs": profit,
        "buy_hold_final_balance": None if profit is None else starting_balance + profit,
    }


def _monte_carlo(
    returns: pd.Series,
    *,
    benchmark_return: float | None = None,
    simulations: int = 5_000,
    seed: int = 42,
) -> dict[str, Any] | None:
    values = returns.to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if not len(values) or not np.any(values):
        return None
    rng = np.random.default_rng(seed)
    equity = np.ones(simulations)
    peak = np.ones(simulations)
    max_drawdown = np.zeros(simulations)
    for _ in values:
        equity *= 1.0 + rng.choice(values, simulations, replace=True)
        peak = np.maximum(peak, equity)
        max_drawdown = np.minimum(max_drawdown, equity / peak - 1.0)
    terminal_returns = equity - 1.0
    return {
        "simulations": simulations,
        "seed": seed,
        "sample_days": len(values),
        "return_p05": _finite(np.quantile(terminal_returns, 0.05)),
        "return_p50": _finite(np.quantile(terminal_returns, 0.50)),
        "return_p95": _finite(np.quantile(terminal_returns, 0.95)),
        "probability_profit": _finite(np.mean(terminal_returns > 0)),
        "probability_beat_buy_hold": (
            None
            if benchmark_return is None
            else _finite(np.mean(terminal_returns > benchmark_return))
        ),
        "drawdown_p05": _finite(np.quantile(max_drawdown, 0.05)),
        "drawdown_p50": _finite(np.quantile(max_drawdown, 0.50)),
    }


def _quantstats_report(
    returns: pd.Series,
    benchmark: pd.Series | None,
    strategy: str,
    market_label: str,
    benchmark_title: str | None,
) -> str | None:
    if returns.empty or not returns.ne(0).any():
        return None
    with tempfile.TemporaryDirectory(prefix="lastdance-quantstats-") as temporary:
        output = Path(temporary) / "report.html"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            warnings.simplefilter("ignore", UserWarning)
            qs.reports.html(
                returns,
                benchmark=benchmark,
                title=f"{strategy} · {market_label}",
                output=str(output),
                periods_per_year=365,
                figfmt="svg",
                strategy_title=f"PnL {strategy}",
                benchmark_title=benchmark_title,
                parameters={"PnL": "USD sobre capital inicial", "HODL": "compra inicial, sin ventas"},
            )
        return output.read_text(encoding="utf-8")


def _fmt_num(value: Any) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number:,.3f}"


def _fmt_money(value: Any) -> str:
    number = _finite(value)
    return "—" if number is None else f"${number:,.2f}"


def _fmt_pct(value: Any) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number * 100:.2f}%"


REPORT_TEMPLATE = Environment(autoescape=True).from_string(
    """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LastDance · Informe consolidado</title><style>
:root{--bg:#071019;--panel:#0e1b28;--panel2:#122436;--line:#263b4d;--text:#eaf2f8;--muted:#91a6b8;--cyan:#47d7c7;--green:#57d89b;--amber:#f4c66a;--red:#ff7f87}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#12314a 0,transparent 32%),var(--bg);color:var(--text);font-family:Inter,"Segoe UI",Arial,sans-serif}main{max-width:1280px;margin:auto;padding:38px 24px 64px}
h1{font-size:34px;margin:0 0 8px;letter-spacing:-.8px}h2{font-size:20px;margin:0 0 16px}h3{font-size:15px;margin:24px 0 10px}.eyebrow{color:var(--cyan);font-size:12px;font-weight:700;letter-spacing:1.8px;text-transform:uppercase}.muted{color:var(--muted)}
.hero,.card{background:linear-gradient(145deg,rgba(18,36,54,.96),rgba(12,26,39,.96));border:1px solid var(--line);border-radius:16px;box-shadow:0 14px 38px rgba(0,0,0,.2)}.hero{padding:26px;margin-bottom:18px}.card{padding:22px;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.metric{background:#0a1722;border:1px solid #21384b;border-radius:12px;padding:14px}.metric small{display:block;color:var(--muted);margin-bottom:7px}.metric strong{font-size:20px}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{padding:11px 10px;border-bottom:1px solid var(--line);text-align:right}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.7px}th:first-child,td:first-child{text-align:left}
.badge{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}.success{color:var(--green);background:#123a31}.no_trades{color:var(--amber);background:#3b3018}.failed,.invalid_data,.invalid_result{color:var(--red);background:#421f28}.valid{color:var(--green)}.invalid{color:var(--red)}
.notice{border-left:3px solid var(--amber);background:#251f13;padding:13px 15px;border-radius:8px;color:#ecd9aa}.error{border-left-color:var(--red);background:#2a171d;color:#ffc8cc}.qs{width:100%;height:1800px;border:1px solid var(--line);border-radius:12px;background:white}details{margin-top:16px}summary{cursor:pointer;color:var(--cyan)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#07131d;border:1px solid var(--line);padding:15px;border-radius:10px;color:#bdd0df;font-size:12px}.footer{font-size:12px;color:var(--muted);margin-top:24px}
@media(max-width:700px){main{padding:24px 12px}h1{font-size:27px}.card,.hero{padding:16px}.qs{height:1300px}}
</style></head><body><main>
<header class="hero"><div class="eyebrow">LastDance · research pipeline</div><h1>Informe consolidado de backtesting</h1><p class="muted">Generado {{ generated }} · {{ market_label }} · USD · periodo evaluado {{ metadata.timerange }}</p><div class="grid"><div class="metric"><small>Fuente de mercado</small><strong>{{ metadata.data_source }}</strong></div><div class="metric"><small>Inicio solicitado</small><strong>{{ metadata.requested_history_start|default('—', true) }}</strong></div><div class="metric"><small>Inicio efectivo</small><strong>{{ metadata.effective_history_start|default('—', true) }}</strong></div><div class="metric"><small>Pares aceptados</small><strong>{{ metadata.pairs|length }}</strong></div><div class="metric"><small>Pares excluidos</small><strong>{{ metadata.pairs_excluded|default([])|length }}</strong></div><div class="metric"><small>Warm-up requerido</small><strong>{{ metadata.startup_candles_required|default('—') }} velas</strong></div></div>{% if metadata.proxy_market_data %}<p class="notice">Las velas son de {{ metadata.exchange_reference }} y se evalúan con Bitso sólo como referencia de ejecución. No son velas de Bitso ni se mezclan con su caché.</p>{% endif %}</header>
<section class="card"><h2>Comparación global</h2><div class="table-wrap"><table><thead><tr><th>Estrategia</th><th>Estado</th><th>Operaciones</th><th>Wins</th><th>Draws</th><th>Losses</th><th>Retorno</th><th>P&amp;L estrategia</th><th>P&amp;L Buy &amp; Hold</th><th>Sharpe</th><th>Sortino</th><th>Máx. DD</th><th>Acierto</th><th>Tiempo</th></tr></thead><tbody>
{% for row in rows %}<tr><td>{{ row.strategy }}</td><td><span class="badge {{ row.status }}">{{ labels.get(row.status,row.status) }}</span></td><td>{{ row.metrics.trades if row.metrics else '—' }}</td><td>{{ row.metrics.wins if row.metrics else '—' }}</td><td>{{ row.metrics.draws if row.metrics else '—' }}</td><td>{{ row.metrics.losses if row.metrics else '—' }}</td><td>{{ fmt_pct(row.metrics.return_total) if row.metrics else '—' }}</td><td>{{ fmt_money(row.metrics.profit_total_abs) if row.metrics else '—' }}</td><td>{{ fmt_money(row.metrics.buy_hold_profit_abs) if row.metrics else '—' }}</td><td>{{ fmt_num(row.metrics.sharpe) if row.metrics else '—' }}</td><td>{{ fmt_num(row.metrics.sortino) if row.metrics else '—' }}</td><td>{{ fmt_pct(row.metrics.max_drawdown) if row.metrics else '—' }}</td><td>{{ fmt_pct(row.metrics.win_rate) if row.metrics else '—' }}</td><td>{{ fmt_num(row.runtime_seconds) }} s</td></tr>{% endfor %}
</tbody></table></div></section>
<section class="card"><h2>Integridad de datos</h2><p class="muted">Cada archivo se verificó por hash, estructura OHLCV, timestamps únicos/alineados y warm-up anterior al periodo.</p><div class="table-wrap"><table><thead><tr><th>Par</th><th>TF</th><th>Estado</th><th>Velas</th><th>Warm-up</th><th>Inicio</th><th>Fin</th><th>Gaps</th><th>SHA-256</th></tr></thead><tbody>{% for item in metadata.data_inventory|default([]) %}<tr><td>{{ item.pair }}</td><td>{{ item.timeframe }}</td><td class="{{ item.quality_status }}">{{ item.quality_status }}</td><td>{{ item.candles }}</td><td>{{ item.warmup_candles }}/{{ item.required_warmup_candles }}</td><td>{{ item.first_candle or '—' }}</td><td>{{ item.last_candle or '—' }}</td><td>{{ item.gap_count }}</td><td title="{{ item.sha256 }}">{{ item.sha256[:12] if item.sha256 else '—' }}</td></tr>{% endfor %}</tbody></table></div>
{% if metadata.pairs_excluded|default([]) %}<h3>Exclusiones</h3>{% for item in metadata.pairs_excluded %}<p class="notice error"><strong>{{ item.pair }}</strong>: {{ item.reasons|join(', ') }}</p>{% endfor %}{% endif %}</section>
{% for row in rows %}<section class="card"><h2>{{ row.strategy }} <span class="badge {{ row.status }}">{{ labels.get(row.status,row.status) }}</span></h2>
{% if row.metrics %}<div class="grid"><div class="metric"><small>Capital inicial</small><strong>{{ fmt_money(row.metrics.starting_balance) }}</strong></div><div class="metric"><small>P&amp;L estrategia</small><strong>{{ fmt_money(row.metrics.profit_total_abs) }}</strong></div><div class="metric"><small>Capital final estrategia</small><strong>{{ fmt_money(row.metrics.final_balance) }}</strong></div><div class="metric"><small>Retorno estrategia</small><strong>{{ fmt_pct(row.metrics.return_total) }}</strong></div><div class="metric"><small>P&amp;L Buy &amp; Hold {{ row.metrics.buy_hold_pair or '' }}</small><strong>{{ fmt_money(row.metrics.buy_hold_profit_abs) }}</strong></div><div class="metric"><small>Capital final Buy &amp; Hold</small><strong>{{ fmt_money(row.metrics.buy_hold_final_balance) }}</strong></div><div class="metric"><small>Retorno Buy &amp; Hold</small><strong>{{ fmt_pct(row.metrics.buy_hold_return) }}</strong></div><div class="metric"><small>Wins / Draws / Losses</small><strong>{{ row.metrics.wins }} / {{ row.metrics.draws }} / {{ row.metrics.losses }}</strong></div><div class="metric"><small>Profit factor</small><strong>{{ '∞' if row.metrics.wins and not row.metrics.losses else fmt_num(row.metrics.profit_factor) }}</strong></div><div class="metric"><small>Expectancy</small><strong>{{ fmt_num(row.metrics.expectancy) }}</strong></div><div class="metric"><small>Máx. drawdown</small><strong>{{ fmt_pct(row.metrics.max_drawdown) }}</strong></div><div class="metric"><small>Máx. drawdown absoluto</small><strong>{{ fmt_money(row.metrics.max_drawdown_abs) }}</strong></div></div>
<p class="muted">{{ row.metrics.backtest_start }} — {{ row.metrics.backtest_end }} · {{ row.metrics.trades }} operaciones · {{ fmt_num(row.metrics.trades_per_day) }} operaciones/día · duración media {{ fmt_num(row.metrics.average_duration_minutes) }} min · días W/D/L {{ row.metrics.winning_days }}/{{ row.metrics.draw_days }}/{{ row.metrics.losing_days }} · racha W/L {{ row.metrics.max_consecutive_wins }}/{{ row.metrics.max_consecutive_losses }} · retornos: {{ row.metrics.return_method }} · diferencia de conciliación {{ fmt_money(row.metrics.reconciliation_difference) }}</p>
{% if row.monte_carlo %}<h3>Monte Carlo · bootstrap diario de P&amp;L</h3><div class="grid"><div class="metric"><small>Retorno percentil 5</small><strong>{{ fmt_pct(row.monte_carlo.return_p05) }}</strong></div><div class="metric"><small>Retorno mediano</small><strong>{{ fmt_pct(row.monte_carlo.return_p50) }}</strong></div><div class="metric"><small>Retorno percentil 95</small><strong>{{ fmt_pct(row.monte_carlo.return_p95) }}</strong></div><div class="metric"><small>Probabilidad de ganancia</small><strong>{{ fmt_pct(row.monte_carlo.probability_profit) }}</strong></div><div class="metric"><small>Probabilidad de superar Buy &amp; Hold</small><strong>{{ fmt_pct(row.monte_carlo.probability_beat_buy_hold) }}</strong></div><div class="metric"><small>Drawdown adverso percentil 5</small><strong>{{ fmt_pct(row.monte_carlo.drawdown_p05) }}</strong></div></div><p class="muted">{{ row.monte_carlo.simulations }} simulaciones · semilla {{ row.monte_carlo.seed }} · {{ row.monte_carlo.sample_days }} días remuestreados. Estima sensibilidad al orden histórico; no modela nuevos regímenes, liquidez ni deslizamiento adicional.</p>{% endif %}
{% if row.quantstats_html %}<h3>QuantStats · P&amp;L realizado vs Buy &amp; Hold (365 periodos/año)</h3><p class="muted">QuantStats compara retornos porcentuales. Los importes monetarios de P&amp;L aparecen arriba; Buy &amp; Hold supone invertir el capital inicial y no vender hasta el final.</p><iframe class="qs" sandbox="allow-scripts" loading="lazy" srcdoc="{{ row.quantstats_html }}" title="QuantStats {{ row.strategy }}"></iframe>{% else %}<p class="notice">QuantStats no se calcula sin retornos realizados distintos de cero. Esto evita presentar ratios indefinidos como si fueran 0.</p>{% endif %}
{% else %}<p class="notice error"><strong>Resultado no publicable.</strong> {{ row.error or 'No existe un export válido.' }}</p>{% endif %}</section>{% endfor %}
<section class="card"><h2>Reproducibilidad</h2><details><summary>Ver metadata completa del run</summary><pre>{{ metadata_json }}</pre></details></section>
<p class="footer">Investigación, no asesoría financiera. Un backtest no garantiza resultados futuros. Los datos proxy, si se habilitan, deben aparecer etiquetados y nunca se presentan como ejecución Bitso.</p>
</main></body></html>"""
)


def generate_report(run_dir: Path, output: Path | None = None) -> Path:
    metadata = read_json(run_dir / "metadata.json")
    metadata.setdefault("pairs", [])
    metadata.setdefault("pairs_excluded", [])
    metadata.setdefault("data_inventory", [])
    market_label = (
        "Alpaca Crypto US (proxy; ejecución Bitso spot)"
        if metadata.get("proxy_market_data")
        else f"{metadata.get('exchange_reference', 'mercado')} spot"
    )
    rows: list[dict[str, Any]] = []
    for outcome in metadata.get("outcomes", []):
        row = {
            **outcome,
            "metrics": None,
            "monte_carlo": None,
            "quantstats_html": None,
            "error": outcome.get("error_tail", ""),
        }
        exports = [Path(value) for value in outcome.get("exports", [])]
        export = next((path for path in exports if path.exists()), None)
        if outcome.get("status") in {"success", "no_trades"} and export:
            try:
                result = _strategy_result(_read_export(export), outcome["strategy"])
                returns, balances = _portfolio_returns(result, _read_wallet(export))
                benchmark, benchmark_pair = _benchmark_returns(metadata, returns)
                metrics = _metrics(result, returns, balances)
                metrics.update(
                    _buy_hold_metrics(
                        benchmark,
                        benchmark_pair,
                        metrics["starting_balance"],
                    )
                )
                row["metrics"] = metrics
                row["monte_carlo"] = _monte_carlo(
                    returns,
                    benchmark_return=metrics["buy_hold_return"],
                )
                row["quantstats_html"] = _quantstats_report(
                    returns,
                    benchmark,
                    outcome["strategy"],
                    market_label,
                    f"Buy & Hold {benchmark_pair}" if benchmark_pair else None,
                )
                if not result["trades"]:
                    row["status"] = "no_trades"
            except (KeyError, OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                row["status"] = "invalid_result"
                row["error"] = f"{exc.__class__.__name__}: {exc}"
        elif outcome.get("status") in {"success", "no_trades"}:
            row["status"] = "invalid_result"
            row["error"] = "Freqtrade no produjo un export de resultados legible."
        rows.append(row)
    output = output or REPORTS_DIR / "latest" / "report.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        REPORT_TEMPLATE.render(
            generated=datetime.now(UTC).isoformat(),
            market_label=market_label,
            metadata=metadata,
            metadata_json=json.dumps(metadata, indent=2, sort_keys=True),
            rows=rows,
            labels={
                "success": "válido",
                "no_trades": "sin operaciones",
                "invalid_data": "datos inválidos",
                "invalid_result": "export inválido",
                "failed": "falló",
            },
            fmt_num=_fmt_num,
            fmt_money=_fmt_money,
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
