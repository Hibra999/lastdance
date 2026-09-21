# Reproducible patches

Patches target the pinned NFI commit. `lastdance.strategies.runtime_patch` applies the documented substitutions only to ignored runtime copies, keeping the NFI submodule unchanged.

## `nfi-v17.5.40-modern-numpy-pandas.patch`

- Upstream commit: `ad5b4b98b52cd72932dd11e464fb8ede3663050c` (`v17.5.40`).
- Reason: X5 assigns Boolean signals into string columns, rejected by Pandas 3; legacy Next uses the removed NumPy 2 aliases `np.NAN` and `np.NaN`.
- Scope: dtype-compatible signal assignment, a nullable object value for mixed text/missing output, and the equivalent `np.nan` spelling. Strategy conditions and parameter values are unchanged.
- Regression proof: enabled strategy imports plus the 5m smoke backtest exercise both patched paths.
