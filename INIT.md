# LastDance initial bootstrap record

## Scope and date

Initial implementation completed on Windows during September 2026. The goal was a reproducible Bitso spot research pipeline using Freqtrade as engine, NFI as strategy source, QuantStats for analytics, and optional CUDA acceleration only where measured.

## Detected system

- Windows 10 64-bit, build 19045.
- Intel Core i9-14900KF: 24 physical cores, 32 logical processors.
- 64 GB RAM.
- NVIDIA GeForce RTX 5070 with 12,227 MiB VRAM.
- NVIDIA driver 610.47; reported compute capability 12.0.
- Miniconda 26.3.2.
- Git and GitHub CLI available; GitHub authenticated as `Hibra999`.
- No usable system `nvcc` was found on `PATH`. CuPy's packaged CUDA runtime works without it.

## Version decisions

Repositories and package requirements were inspected before implementation. Selected pins:

- Python 3.13.15.
- Freqtrade 2026.8, upstream commit `9f10e357a93c1dcf10c2a2b367659214d89c073e`.
- NFI v17.5.40, commit `ad5b4b98b52cd72932dd11e464fb8ede3663050c`.
- QuantStats 0.0.81, commit `fbd10daed0227aa0d10da6513f1b15e7e98d7fae`.
- CCXT 4.5.78.
- TA-Lib 0.7.1.
- CuPy CUDA 13x 14.2.0 with packaged CUDA toolkit components.

Python 3.13 gave the newest stable shared range across the selected releases. NFI requires Python 3.12 or newer, Freqtrade supports Python 3.11 or newer, and QuantStats supports Python 3.10 or newer. The resulting environment installed and passed imports and tests on native Windows.

## Architecture decisions

- Freqtrade remains the only trading/backtesting/dry-run engine.
- NFI is a pinned Git submodule, not a copied or modified fork.
- LastDance adapters are isolated in the `lastdance` package.
- No upstream patch was required.
- Generated market data, logs, run exports, pair snapshots, and reports stay outside Git history.
- Runtime Freqtrade files remain credential-free; environment variables carry secrets.
- Live trading remains unavailable from the LastDance CLI.

## NFI inspection

NFI's current recommended configuration selects `NostalgiaForInfinityX7`. X7 and maintained X6 were enabled. X through X5 parsed successfully but were disabled because they are superseded. `NostalgiaForInfinityNext` and `NextGen` remain disabled because upstream stores them under `legacy/`.

Both enabled strategies import under Freqtrade 2026.8 with interface version 3, 5-minute timeframe, and 800 startup candles. NFI parameters were not tuned or changed.

## Bitso findings

Freqtrade 2026.8 recognizes Bitso as a valid generic CCXT exchange but warns that it is not officially supported. Spot validation reports optional gaps in `fetchTickers`, `fetchOrders`, and `watchOHLCV`.

CCXT verified `fetchMarkets`, `fetchTicker`, `fetchTrades`, `fetchOHLCV`, `fetchBalance`, `fetchOrder`, `fetchOpenOrders`, `createOrder`, and `cancelOrder`. `fetchTickers` is unavailable.

Public discovery returned 54 markets and 26 USD spot candidates. A 14-day 5-minute history check retained 21 pairs. `BAR/USD`, `ENJ/USD`, `MANA/USD`, and `PSG/USD` lacked recent candles; `EUR/USD` was excluded as fiat/fiat. No custom exchange adapter was justified.

Read-only account verification completed without credentials. Public API reachable, authentication skipped, orders placed: zero.

## Historical data and backtest proof

Real Bitso `BTC/USD` candles were downloaded for `5m`, `15m`, `1h`, `4h`, and `1d`. The local sample spans approximately 2026-08-03 through 2026-09-17, with 13,009 five-minute candles.

X7 and X6 were backtested concurrently for timerange `20260903-` against Bitso data. Both Freqtrade processes returned code 0. Both produced zero trades for the short sample. This confirms engine, strategy loading, informative data, scheduling, exports, metadata, and reporting paths without claiming profitability.

The consolidated report is generated at `reports/latest/report.html` and identifies successful, failed, and zero-trade strategies.

## Performance findings

Benchmark input: 1,000,000 deterministic price values.

- Python loop baseline: 0.18749456 seconds.
- Vectorized NumPy: 0.00279430 seconds.
- CuPy including transfer: 0.00647650 seconds.
- CPU and GPU results numerically equivalent.
- Automatic backend: CPU.
- Selected speedup over baseline: 67.0989x.
- Peak measured CPU allocation: 24,000,464 bytes.

CUDA was functional but slower for this transfer-heavy operation. No claim of GPU acceleration is made; the measured CPU implementation remains selected.

## Problems and minimal solutions

- Bitso lacks `fetchTickers`: dynamic discovery uses `load_markets` and optional per-pair OHLCV checks instead of falsifying capability support.
- Freqtrade marks Bitso unsupported: retained generic adapter, documented warning, and added integration tests.
- NFI needs several informative timeframes: downloader requests all five required timeframes before backtesting.
- GPU transfer overhead exceeded compute benefit: `auto` selects NumPy CPU while retaining equivalent opt-in GPU path.
- Freqtrade exports initially collided across concurrent strategies: each strategy now writes to its own backtest directory.
- No system CUDA compiler was available: installed CuPy's compatible packaged toolkit; custom CUDA compilation remains out of scope.
- Alpaca data differs from Bitso: alternative adapter records explicit proxy provenance and never participates in default pipeline.

## Final operational state

- Conda environment `lastdance` exists and is reproducible from `environment.yml`.
- Default configuration is Bitso spot, USD, dry-run enabled, live disabled.
- Windows PowerShell and batch launchers exist.
- NFI update checker performs candidate checkout, compatibility test, and rollback on failure.
- Tests cover configuration, strategies, pair filtering, secrets, data normalization, Alpaca provenance, reporting, CPU/GPU equivalence, CLI, and Freqtrade/Bitso integration.
- Repository remote is `https://github.com/Hibra999/lastdance.git` on branch `main`.
- No real orders were placed during bootstrap or verification.
