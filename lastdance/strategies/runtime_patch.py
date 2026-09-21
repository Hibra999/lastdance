from __future__ import annotations

from pathlib import Path

from lastdance.paths import RESULTS_DIR

REPLACEMENTS = {
    "NostalgiaForInfinityX5": (
        ('df.loc[:, "enter_long"] = ""', 'df.loc[:, "enter_long"] = 0'),
        ('df.loc[:, "enter_short"] = ""', 'df.loc[:, "enter_short"] = 0'),
        ('df.loc[:, "enter_long"] = item_long_entry', 'df.loc[:, "enter_long"] = item_long_entry.astype(int)'),
        (
            'df.loc[:, "enter_long"] = reduce(lambda x, y: x | y, long_entry_conditions)',
            'df.loc[:, "enter_long"] = reduce(lambda x, y: x | y, long_entry_conditions).astype(int)',
        ),
        ('df.loc[:, "enter_short"] = item_short_entry', 'df.loc[:, "enter_short"] = item_short_entry.astype(int)'),
        (
            'df.loc[:, "enter_short"] = reduce(lambda x, y: x | y, short_entry_conditions)',
            'df.loc[:, "enter_short"] = reduce(lambda x, y: x | y, short_entry_conditions).astype(int)',
        ),
    ),
    "NostalgiaForInfinityNext": (
        (
            'np.where((mavalue < pm_arr), "down", "up"), np.NaN)',
            'np.where((mavalue < pm_arr), "down", "up"), None)',
        ),
        ('np.where(dataframe["close"] < smaLow, -1, np.NAN)', 'np.where(dataframe["close"] < smaLow, -1, np.nan)'),
    ),
}


def prepare_strategy_path(name: str, source: Path) -> Path:
    replacements = REPLACEMENTS.get(name)
    if not replacements:
        return source.parent
    text = source.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"Compatibility patch no longer matches {source.name}: {old}")
        text = text.replace(old, new, 1)
    target_dir = RESULTS_DIR / "runtime" / "strategies" / name
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / source.name).write_text(text, encoding="utf-8")
    return target_dir
