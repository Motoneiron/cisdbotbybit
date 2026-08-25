"""Фильтр объёма: vol/SMA на trigger-баре (KEEP LOW или KEEP HIGH)."""
from __future__ import annotations

import pandas as pd


def volume_ratio_series(df: pd.DataFrame, ma_period: int = 20) -> pd.Series:
    ma = df["volume"].rolling(ma_period, min_periods=ma_period).mean()
    return df["volume"] / ma


def trigger_vol_max_ok(
    ratios: pd.Series,
    trigger_idx: int,
    *,
    max_ratio: float,
) -> bool:
    """KEEP LOW: pass если vol/SMA <= max_ratio на trigger-баре."""
    if max_ratio <= 0:
        return True
    if trigger_idx < 0 or trigger_idx >= len(ratios):
        return False
    r = ratios.iloc[trigger_idx]
    if pd.isna(r):
        return False
    return float(r) <= max_ratio


def filter_signals_by_volume(
    signals: list[dict],
    ratios: pd.Series,
    min_ratio: float,
) -> list[dict]:
    if min_ratio <= 0:
        return list(signals)
    out: list[dict] = []
    for sig in signals:
        i = sig["trigger_global"]
        if i >= len(ratios):
            continue
        r = ratios.iloc[i]
        if pd.isna(r) or r < min_ratio:
            continue
        out.append(sig)
    return out


def attach_volume_ratios(signals: list[dict], ratios: pd.Series) -> None:
    for sig in signals:
        i = sig["trigger_global"]
        sig["vol_ratio"] = float(ratios.iloc[i]) if i < len(ratios) and not pd.isna(ratios.iloc[i]) else None
