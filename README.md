# LastDance

LastDance is a Windows-native research pipeline for running current NostalgiaForInfinity (NFI) strategies on Freqtrade with Bitso spot market data. It discovers the Bitso/USD universe, downloads candles, runs enabled strategies concurrently, validates CPU/GPU numeric equivalence, and produces one consolidated HTML report.

> Research software only. Backtests and dry-runs do not guarantee future results. Live trading is not implemented by this CLI and remains blocked by default.

## Current validated stack

| Component | Pinned version | Source commit |
|---|---:|---|
| Python | 3.13.15 | Conda-forge |
| Freqtrade | 2026.8 | `9f10e357a93c1dcf10c2a2b367659214d89c073e` |
| NFI | v17.5.40 | `ad5b4b98b52cd72932dd11e464fb8ede3663050c` |
| QuantStats | 0.0.81 | `fbd10daed0227aa0d10da6513f1b15e7e98d7fae` |
| CCXT | 4.5.78 | PyPI |
| TA-Lib | 0.7.1 | PyPI |
| CuPy | 14.2.0 (`cupy-cuda13x[ctk]`) | PyPI |

Python 3.13 was selected because the pinned Freqtrade, NFI, QuantStats, CCXT, TA-Lib, and CuPy releases install and run together on Windows. NFI requires Python 3.12 or newer; the project constrains Python to `>=3.12,<3.14`.

## Architecture

```text
config/                 User-controlled application, pair, strategy, and Freqtrade defaults
lastdance/              Small orchestration layer; no copied upstream trading logic
scripts/                Windows bootstrap, launchers, verification, secret scan, NFI updater
tests/                  Unit and integration coverage
third_party/            Pinned NFI Git submodule and upstream lock file
user_data/data/         Local Freqtrade candle cache; ignored by Git
results/                Run metadata, logs, exports, pair snapshots; ignored by Git
reports/latest/         Single consolidated HTML report; ignored by Git
patches/                Reproducible upstream patches, currently empty
```

Freqtrade owns trading, backtesting, and dry-run behavior. NFI stays a pinned submodule and supplies strategies and recommended blacklists. LastDance only owns discovery, safe runtime configuration, scheduling, provenance, benchmarks, and reporting. No upstream source is modified.

## Requirements

- Windows 10/11 64-bit.
- Miniconda or Anaconda available as `conda`.
- Git.
- Internet access to GitHub, Bitso, and package indexes.
- NVIDIA GPU is optional. CPU fallback always works.
- Docker and WSL are not required.

If Miniconda is not installed, install the current Windows x86-64 build from the official Conda documentation, open a new PowerShell session, and confirm `conda --version`.

## Installation

Clone with the NFI submodule, then run the bootstrap:

```powershell
git clone --recurse-submodules https://github.com/Hibra999/lastdance.git
cd lastdance
.\scripts\bootstrap.ps1
```

For an existing clone:

```powershell
git submodule update --init --recursive
.\scripts\bootstrap.ps1
```

The script creates or updates the `lastdance` Conda environment from `environment.yml`, installs the project in editable mode, and runs the environment doctor. Recreate a damaged environment with:

```powershell
.\scripts\bootstrap.ps1 -Recreate
```

Activate manually when needed:

```powershell
.\scripts\activate.ps1
```

## Configuration

Main settings live in:

- `config/app.yaml`: exchange, history, concurrency, acceleration, reports, and safety defaults.
- `config/strategies.yaml`: enable or disable NFI strategies without editing Python.
- `config/pairs.yaml`: manual exclusions and NFI-derived blacklist sources.
- `config/freqtrade/base.json`: safe Freqtrade spot/dry-run defaults.

Generated runtime configurations contain no credentials. Secrets reach Freqtrade through environment variables only.

## Secrets

Copy `.env.example` to `.env` and fill only values you need:

```powershell
Copy-Item .env.example .env
```

Supported variables:

```text
BITSO_API_KEY
BITSO_API_SECRET
ALPACA_API_KEY
ALPACA_API_SECRET
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
LIVE_TRADING
```

`.env` is ignored by Git. Never place credentials in YAML, JSON, source code, reports, logs, tests, or commits. Run the scanner before every commit:

```powershell
conda run -n lastdance python scripts/scan_secrets.py
```

## Main commands

```powershell
conda run -n lastdance python -m lastdance doctor
conda run -n lastdance python -m lastdance pairs --validate-history
conda run -n lastdance python -m lastdance strategies --freqtrade
conda run -n lastdance python -m lastdance data
conda run -n lastdance python -m lastdance benchmark
conda run -n lastdance python -m lastdance backtest --workers 1
conda run -n lastdance python -m lastdance report --open
conda run -n lastdance python -m lastdance verify-bitso
conda run -n lastdance python -m lastdance dry-run
conda run -n lastdance python -m lastdance all --smoke --open
```

Full pipeline launchers:

```powershell
.\scripts\run_backtests.ps1
.\scripts\run_backtests.ps1 -Smoke
```

```bat
scripts\run_backtests.bat --smoke
```

`all` discovers pairs, benchmarks acceleration, updates candles, runs every enabled strategy, writes metadata, generates `reports/latest/report.html`, and optionally opens it.

## Bitso

Bitso is valid in Freqtrade 2026.8 through the generic CCXT exchange implementation, but Freqtrade does not classify it as an officially supported exchange. Current spot validation reports missing optional capabilities `fetchTickers`, `fetchOrders`, and `watchOHLCV`; these are not required for the validated backtest path.

CCXT 4.5.78 capability snapshot:

| Capability | Available |
|---|---:|
| `fetchMarkets` | yes |
| `fetchTicker` | yes |
| `fetchTickers` | no |
| `fetchTrades` | yes |
| `fetchOHLCV` | yes |
| `fetchBalance` | yes |
| `fetchOrder` | yes |
| `fetchOpenOrders` | yes |
| `createOrder` | yes |
| `cancelOrder` | yes |

The verified public snapshot contained 54 markets and 26 USD spot candidates. History validation retained 21 pairs. Each excluded pair records its reason. The snapshot is regenerated into `results/pairs/latest.json` and is intentionally not committed because exchange state changes.

`verify-bitso` performs public discovery, reports capabilities, checks HTTPS server-time offset, validates Freqtrade integration, and reads balances only when credentials exist. It never creates, edits, or cancels an order.

## NFI strategies

NFI's current `recommended_config.json` selects `NostalgiaForInfinityX7`. LastDance preserves each enabled strategy's upstream main timeframe:

| Strategy | Default | Status | Reason |
|---|---:|---|---|
| NostalgiaForInfinityX7 | enabled | supported | Current upstream recommendation |
| NostalgiaForInfinityX6 | enabled | supported | Maintained comparison generation |
| X5, X4, X3, X2, X | enabled | historical | Superseded generations retained for comparison |
| NostalgiaForInfinityNext | enabled | legacy | Legacy 5m comparison |
| NostalgiaForInfinityNextGen | enabled | legacy | Runs at its upstream 15m main timeframe |

All enabled sources are imported through the installed Freqtrade stack and smoke-backtested. X5 and Next receive the minimal reproducible NumPy/Pandas compatibility patch documented under `patches/`; trading conditions and parameters are unchanged. The 5m strategies keep NFI's required 15m, 1h, 4h, and 1d informative frames. NextGen runs at 15m. LastDance does not tune NFI parameters.

Toggle a strategy in `config/strategies.yaml`:

```yaml
strategies:
  NostalgiaForInfinityX7:
    enabled: true
```

## Historical data and Alpaca

The default historical source is Alpaca Crypto US. Required NFI timeframes are `5m`, `15m`, `1h`, `4h`, and `1d`. Alpaca Feather files live under `user_data/data/alpaca`, separate from Bitso files.

Downloads expand each timeframe independently by NFI's 800 startup candles plus a gap margin. Coverage metadata prevents repeated historical requests; subsequent runs fetch only an uncovered prefix or candles after the cached tail. Duplicate timestamps are merged only when their OHLCV values agree, and any gap longer than seven days excludes that pair from a run.

Historical crypto requests work anonymously; `ALPACA_API_KEY` and `ALPACA_API_SECRET` are optional and, when used, must both be set. Alpaca records always contain:

```text
data_source=alpaca
exchange_reference=alpaca_crypto_us
proxy_market_data=true
```

Alpaca candles are never labeled as Bitso data and are never silently mixed with Bitso candles. Reports identify Alpaca as a proxy and Bitso only as the execution reference.

## Backtesting

No Hyperopt or parameter fine-tuning is performed. Independent strategies run concurrently with a conservative worker count derived from CPU and available RAM. A failed strategy is recorded while remaining strategies continue.

Each run stores:

- LastDance and NFI Git revisions.
- Python, OS, Freqtrade, CCXT, QuantStats, and TA-Lib versions.
- Pairs, strategies, timerange, timeframes, workers, and acceleration mode.
- Per-file SHA-256, candle provenance, first/last timestamps, gaps, alignment, and warm-up proof.
- Requested, accepted, and excluded pairs with reasons.
- Per-strategy status (`success`, `no_trades`, `invalid_data`, `invalid_result`, or `failed`), runtime, log, and Freqtrade export.

A validated run covers `2023-03-12` through `2026-09-21` with Alpaca `BTC/USD` and `DOGE/USD`, complete 800-candle daily warm-up, and all eight 5m strategies. The requested 2020 lower bound is recorded, but Alpaca Crypto US begins on 2021-01-01; preserving NFI's 800 daily startup candles makes 2023-03-12 the first valid signal date. `SOL/USD` is excluded because Alpaca contains a 417-day gap.

From a $10,000 starting wallet, the validated run produced 1–29 trades per strategy. The largest results were X5 with 11 trades and $619.04, X6 with 9 trades and $503.22, and Next with 29 trades and $314.36. These are research results from proxy market data, not forecasts or Bitso fills. A valid zero-trade run is reported as `no_trades`, never as a successful performance result.

## CUDA and performance

`acceleration.mode` defaults to `auto`. The benchmark compares:

1. Python-loop reference.
2. Vectorized NumPy CPU implementation.
3. CuPy GPU implementation including host/device transfer.

The GPU path is selected only when numerically equivalent and faster. On the validated RTX 5070 with 1,000,000 values:

| Measurement | Result |
|---|---:|
| Python baseline | 0.187495 s |
| NumPy CPU | 0.002794 s |
| CuPy GPU | 0.006477 s |
| Selected backend | CPU |
| Speedup vs baseline | 67.10x |
| CPU/GPU equivalent | yes |

The NVIDIA driver exposed CUDA 13.3 compatibility and CuPy used its packaged CUDA 13 runtime. A system `nvcc` is optional; `doctor` reports it separately. GPU availability does not mean GPU use.

## QuantStats report

LastDance generates one self-contained report at `reports/latest/report.html`. Portfolio returns come from Freqtrade's mark-to-market wallet curve, are sampled on a complete daily calendar, and reconcile to the exported final balance. Crypto risk statistics use 365 periods per year. The report embeds the native QuantStats tear sheet for every strategy with non-zero returns, includes a Bitso BTC/USD benchmark, and displays data-integrity evidence and full reproducibility metadata. Failed, invalid-data, invalid-export, and zero-trade strategies remain visible without fabricated ratios.

## Telegram

Freqtrade's native Telegram integration is used. Keep the token and chat ID in `.env`. To enable it for dry-run, also set:

```text
FREQTRADE__TELEGRAM__ENABLED=true
```

Then start:

```powershell
conda run -n lastdance python -m lastdance dry-run --start
```

Freqtrade supplies its current native commands, including status, profit, balance, start, stop, trades, and performance where supported. Messages use bot name `lastdance-dry-run`.

## Trading safety

- `dry_run=true` and `live_enabled=false` are mandatory defaults.
- `python -m lastdance dry-run` only prepares and prints a credential-free runtime file.
- `--start` starts Freqtrade in dry-run mode.
- Runtime files reject embedded Bitso and Telegram secrets.
- Building any non-dry runtime requires both `LIVE_TRADING=true` and `LASTDANCE_LIVE_ACK=I_UNDERSTAND_REAL_ORDERS`.
- LastDance exposes no live-trading CLI command.

## Updating upstreams

Check NFI without changing the checkout:

```powershell
conda run -n lastdance python scripts/sync_nfi.py
```

Apply a candidate release and run strategy compatibility tests:

```powershell
conda run -n lastdance python scripts/sync_nfi.py --apply
```

A failing update rolls back automatically. A passing update still requires review of NFI release notes, `config/strategies.yaml`, `third_party/UPSTREAMS.lock.json`, all tests, and a smoke backtest before commit.

Freqtrade and QuantStats updates are deliberate dependency changes: update pins, record upstream commits, run the full suite, rerun Bitso capability checks, and compare backtest output before accepting them.

## Tests

```powershell
conda run -n lastdance ruff check .
conda run -n lastdance python -m pytest -q
conda run -n lastdance python scripts/scan_secrets.py
```

Integration tests contact Bitso's public API. No test places an order.

## Troubleshooting

- **Conda not found:** reopen PowerShell after Miniconda installation or run `conda init powershell` once.
- **NFI files missing:** run `git submodule update --init --recursive`.
- **Bitso warning about unsupported exchange:** expected for the generic Freqtrade integration; rerun `verify-bitso` and integration tests after every dependency update.
- **No `nvcc`:** CuPy's `[ctk]` package includes required runtime components. Install a system toolkit only for custom CUDA compilation.
- **Zero trades:** widen timerange and confirm all informative timeframes are present; do not tune parameters merely to force trades.
- **GPU slower than CPU:** expected for transfer-heavy operations. Keep `acceleration.mode: auto`.
- **Report missing:** complete a backtest, then run `python -m lastdance report --open`.

## License and upstreams

LastDance is GPL-3.0-or-later. NFI remains governed by its upstream license as a Git submodule. Freqtrade, QuantStats, CCXT, and other dependencies retain their own licenses.
