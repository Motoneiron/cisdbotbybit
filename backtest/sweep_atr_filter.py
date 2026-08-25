"""Sweep size vs ATR(14) at trigger bar — shared BT/live helper."""
from __future__ import annotations

import pandas as pd


def compute_atr14(df: pd.DataFrame) -> pd.Series:
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(14).mean()


def sweep_atr_ratio(
    df: pd.DataFrame,
    trigger_idx: int,
    sweep_level: float,
    is_bearish: bool,
    *,
    atr14: pd.Series | None = None,
) -> float | None:
    if trigger_idx < 0 or trigger_idx >= len(df):
        return None
    if atr14 is None:
        atr14 = compute_atr14(df)
    atr_at = float(atr14.iloc[trigger_idx])
    if pd.isna(atr_at) or atr_at <= 0:
        return None
    row = df.iloc[trigger_idx]
    if is_bearish:
        sweep_size = float(row["high"]) - float(sweep_level)
    else:
        sweep_size = float(sweep_level) - float(row["low"])
    if sweep_size <= 0:
        return 0.0
    return sweep_size / atr_at


def sweep_min_atr_ok(
    df: pd.DataFrame,
    trigger_idx: int,
    sweep_level: float,
    is_bearish: bool,
    *,
    min_ratio: float,
    atr14: pd.Series | None = None,
) -> bool:
    if min_ratio <= 0:
        return True
    ratio = sweep_atr_ratio(
        df, trigger_idx, sweep_level, is_bearish, atr14=atr14,
    )
    if ratio is None:
        return False
    return ratio >= min_ratio
