"""Session VWAP filter (TZ v6: typical price, UTC day, vd vs ATR14)."""
from __future__ import annotations

import pandas as pd


def daily_session_vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP reset at UTC day boundary.

    typical_price = (high + low + close) / 3, as in TZ v6.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    day = df.index.floor("D")
    vol_cum = df["volume"].groupby(day).cumsum()
    pv_cum = pv.groupby(day).cumsum()
    return pv_cum / vol_cum


def vwap_dev_ok(direction: str, vd: float) -> bool:
    """Causal vwap gate: SHORT vd≤0, LONG vd≥0."""
    if direction == "SHORT":
        return vd <= 0.0
    if direction == "LONG":
        return vd >= 0.0
    return False


def vwap_filter_ok(
    direction: str,
    entry_px: float,
    vwap: float,
    *,
    mode: str = "with",
    min_dist_pct: float = 0.0,
) -> bool:
    if not mode or mode == "off":
        return True
    if entry_px <= 0 or vwap <= 0 or pd.isna(vwap):
        return True
    dist = abs(entry_px - vwap) / vwap
    if min_dist_pct > 0 and dist < min_dist_pct:
        return False
    if mode == "with":
        return (direction == "LONG" and entry_px > vwap) or (
            direction == "SHORT" and entry_px < vwap
        )
    if mode == "against":
        return (direction == "LONG" and entry_px < vwap) or (
            direction == "SHORT" and entry_px > vwap
        )
    return True
