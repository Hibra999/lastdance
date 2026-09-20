# LastDance agent guide

## Scope

LastDance is a Windows-native orchestration layer around pinned Freqtrade, NFI, Bitso/CCXT, QuantStats, and optional CuPy. Keep custom code under `lastdance/`. Keep NFI unchanged under `third_party/NostalgiaForInfinity` unless an upstream patch is unavoidable and reproducible.

## Non-negotiable safety

- Never commit, log, print, or embed real API keys, secrets, Telegram tokens, chat IDs, balances, or private account data.
- Credentials belong only in ignored `.env` or process environment variables. Keep `.env.example` empty.
- Keep `dry_run=true` and `live_enabled=false` by default.
- Never place a real order for setup, tests, diagnosis, or compatibility checks.
- Do not claim Bitso is officially supported by Freqtrade. It currently passes generic spot validation with optional capabilities missing.
- Do not label Alpaca data as Bitso data or mix venues silently.
- Do not use Hyperopt or tune NFI parameters unless a future user explicitly changes scope.
- Trading correctness and provenance outrank speed.

## Architecture ownership

- `config/`: human-controlled settings and registry.
- `lastdance/exchanges/`: Bitso discovery, capability reporting, safe Freqtrade runtime configuration.
- `lastdance/data/`: download orchestration, normalization, and explicitly labeled alternative sources.
- `lastdance/strategies/`: registry and compatibility inspection; no copied NFI strategy logic.
- `lastdance/backtesting/`: concurrent independent Freqtrade runs and complete metadata.
- `lastdance/acceleration/`: measured, equivalent CPU/GPU utilities only.
- `lastdance/reporting/`: one consolidated report.
- `third_party/NostalgiaForInfinity`: pinned Git submodule.
- `results/`, `reports/`, `logs/`, `user_data/data/`: generated and ignored except `.gitkeep` files.

## Required checks

Run these before every commit and push:

```powershell
conda run -n lastdance ruff check .
conda run -n lastdance python -m pytest -q
conda run -n lastdance python scripts/scan_secrets.py
```

For exchange, dependency, strategy, or configuration changes also run:

```powershell
conda run -n lastdance python -m lastdance doctor
conda run -n lastdance python -m lastdance verify-bitso
conda run -n lastdance python -m lastdance strategies --freqtrade
conda run -n lastdance python -m lastdance all --smoke
```

Treat any unexplained backtest signal or metric change as a regression until proven otherwise.

## Common operations

```powershell
.\scripts\bootstrap.ps1
conda run -n lastdance python -m lastdance pairs --validate-history
conda run -n lastdance python -m lastdance data --days 45 --pairs BTC/USD
conda run -n lastdance python -m lastdance backtest --days 14 --pairs BTC/USD
conda run -n lastdance python -m lastdance report --open
conda run -n lastdance python -m lastdance dry-run
```

`dry-run` without `--start` prepares configuration only. `dry-run --start` may contact authenticated APIs but must remain Freqtrade dry-run.

## Strategy changes

1. Inspect NFI release notes and recommended configuration.
2. Add or update metadata in `config/strategies.yaml`.
3. Preserve upstream timeframe, ROI, stoploss, exits, protections, DCA, startup candles, and informative pairs.
4. Parse every registered source and import each enabled strategy through the installed stack.
5. Run a smoke backtest before enabling a strategy.
6. Document why obsolete, legacy, experimental, or incompatible strategies remain disabled.

Users must be able to enable or disable a strategy through YAML without Python edits.

## Updating NFI

Run `python scripts/sync_nfi.py` to check. Use `--apply` only for a deliberate candidate update. A passing checkout is not final: update the submodule gitlink, release and commit in `config/strategies.yaml`, and `third_party/UPSTREAMS.lock.json`; then run all required checks and compare results. Do not silently promote an incompatible strategy.

Freqtrade or QuantStats updates require the same pinned-version workflow and a fresh Bitso capability report. Store upstream fixes as minimal files under `patches/` with reason, source commit, and regression test.

## GPU rules

- Keep CPU reference behavior.
- Benchmark before and after optimization.
- Require numeric equivalence at configured tolerances.
- Include transfers in GPU timing.
- Let `auto` choose CPU when GPU is slower.
- Never rewrite NFI indicators or move full DataFrames to GPU without measured benefit and signal-equivalence tests.

Validate with:

```powershell
conda run -n lastdance python -m lastdance benchmark
```

## Git discipline

- Make focused descriptive commits.
- Confirm remote remains `https://github.com/Hibra999/lastdance.git`.
- Never force-push unless the user explicitly requests it.
- Before push inspect `git status`, `git diff --check`, and staged content.
- Scan both working tree and published history for secrets.
