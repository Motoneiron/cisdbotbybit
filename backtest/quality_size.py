#!/usr/bin/env python3
"""Lever-1 quality sizing for live CISDBOT (no KAMA).

Causal score at confirm (same spirit as research L2 score):
  start_n_score + never + unreclaim + no_start_fvg + no_conf_fvg
  + compact_proxy + fast_mss_proxy

Live cannot use in-sample percentile ranks → absolute proxies calibrated
to research medians (start_range_atr ~2–3, bars1 ~15–30).

Size map ≈ mild q5_score (0.60…1.25) via piecewise-linear on score.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

# Research mild quintile sizes vs score medians (sol_quality / lever1).
_SCORE_SIZE_KNOTS: list[tuple[float, float]] = [
    (-2.0, 0.60),
    (0.21, 0.60),
    (2.61, 0.85),
    (4.24, 1.00),
    (6.20, 1.10),
    (7.77, 1.25),
    (10.0, 1.35),
]


def start_n_score(n: int) -> float:
    m = {1: 3, 2: 2, 3: 1, 4: 0, 5: -1}
    return float(m.get(int(n), -2))


def size_mult_from_score(score: float) -> float:
    """Piecewise-linear size in ~[0.60, 1.35]."""
    s = float(score)
    knots = _SCORE_SIZE_KNOTS
    if s <= knots[0][0]:
        return knots[0][1]
    if s >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= s <= x1:
            if x1 == x0:
                return y1
            t = (s - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return 1.0


def _fvg_counts(df: pd.DataFrame, i0: int, i1: int) -> tuple[int, int]:
    bull = bear = 0
    for i in range(max(int(i0), 2), int(i1) + 1):
        if i >= len(df):
            break
        hi2 = float(df.iloc[i - 2]["high"])
        lo = float(df.iloc[i]["low"])
        hi = float(df.iloc[i]["high"])
        lo2 = float(df.iloc[i - 2]["low"])
        if lo > hi2:
            bull += 1
        if hi < lo2:
            bear += 1
    return bull, bear


def never_close_reclaim_1m(
    df1: Optional[pd.DataFrame],
    *,
    direction: str,
    level: float,
    trig_t: pd.Timestamp,
    conf_t: pd.Timestamp,
) -> bool:
    """True if no 1m close reclaimed level between trigger and confirm close."""
    if df1 is None or len(df1) == 0 or level <= 0:
        return False
    conf_end = pd.Timestamp(conf_t) + pd.Timedelta(minutes=1)
    sl = df1[(df1.index >= pd.Timestamp(trig_t)) & (df1.index + pd.Timedelta(minutes=1) <= conf_end)]
    if len(sl) == 0:
        return False
    swept = False
    for j in range(len(sl)):
        b = sl.iloc[j]
        bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
        if direction == "SHORT":
            if bh >= level:
                swept = True
            if swept and bc < level:
                return False
        else:
            if bl <= level:
                swept = True
            if swept and bc > level:
                return False
    return True


def compute_quality_features(
    df5: pd.DataFrame,
    *,
    direction: str,
    trigger_idx: int,
    start_idx: Optional[int],
    confirm_idx_5m: Optional[int],
    level: float,
    atr: float,
    df1: Optional[pd.DataFrame] = None,
    trigger_bar_time: Optional[Any] = None,
    confirm_bar_time: Optional[Any] = None,
) -> dict:
    """Build causal quality features available at MSS confirm."""
    out = {
        "start_n": 0,
        "start_range_atr": np.nan,
        "start_fvg_with": 0,
        "conf_fvg_with": 0,
        "no_start_fvg": True,
        "no_conf_fvg": True,
        "bars1": 0,
        "never": False,
        "unreclaim": False,
        "quality_score": 0.0,
        "quality_size_mult": 1.0,
    }
    if trigger_idx < 0 or trigger_idx >= len(df5) or level <= 0:
        return out
    if not np.isfinite(atr) or atr <= 0:
        atr = float("nan")

    row = df5.iloc[int(trigger_idx)]
    cl = float(row["close"])
    if direction == "LONG":
        unreclaim = cl <= level
    else:
        unreclaim = cl >= level
    out["unreclaim"] = bool(unreclaim)

    si = int(start_idx) if start_idx is not None else int(trigger_idx)
    si = max(0, min(si, int(trigger_idx)))
    start_n = int(trigger_idx) - si + 1
    out["start_n"] = start_n
    sl = df5.iloc[si : int(trigger_idx) + 1]
    if len(sl) and np.isfinite(atr) and atr > 0:
        out["start_range_atr"] = float(sl["high"].max() - sl["low"].min()) / atr

    bull_s, bear_s = _fvg_counts(df5, si, int(trigger_idx))
    start_fvg = bull_s if direction == "SHORT" else bear_s
    out["start_fvg_with"] = int(start_fvg)
    out["no_start_fvg"] = start_fvg == 0

    ci = int(confirm_idx_5m) if confirm_idx_5m is not None else int(trigger_idx)
    ci = max(int(trigger_idx), min(ci, len(df5) - 1))
    if ci > int(trigger_idx):
        bull_c, bear_c = _fvg_counts(df5, int(trigger_idx) + 1, ci)
        conf_fvg = bear_c if direction == "SHORT" else bull_c
    else:
        conf_fvg = 0
    out["conf_fvg_with"] = int(conf_fvg)
    out["no_conf_fvg"] = conf_fvg == 0

    bars1 = 0
    never = False
    if trigger_bar_time is not None and confirm_bar_time is not None:
        try:
            tt = pd.Timestamp(trigger_bar_time)
            ct = pd.Timestamp(confirm_bar_time)
            bars1 = max(0, int((ct - tt).total_seconds() // 60))
            never = never_close_reclaim_1m(
                df1, direction=direction, level=level, trig_t=tt, conf_t=ct,
            )
        except Exception:
            bars1 = max(0, (ci - int(trigger_idx)) * 5)
    else:
        bars1 = max(0, (ci - int(trigger_idx)) * 5)
    out["bars1"] = int(bars1)
    out["never"] = bool(never)

    # Absolute proxies for research rank terms
    sra = out["start_range_atr"]
    compact = 0.5
    if np.isfinite(sra):
        compact = float(np.clip(1.0 - float(sra) / 3.5, 0.0, 1.0))
    fast = float(np.clip(1.0 - float(bars1) / 45.0, 0.0, 1.0))

    score = (
        start_n_score(start_n)
        + float(never)
        + float(unreclaim)
        + float(out["no_start_fvg"])
        + float(out["no_conf_fvg"])
        + compact
        + fast
    )
    out["quality_score"] = round(float(score), 4)
    out["quality_size_mult"] = round(size_mult_from_score(score), 4)
    return out
