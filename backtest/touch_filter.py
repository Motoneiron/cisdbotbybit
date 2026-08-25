"""Prior touches near HTF sweep level — shared live/BT helper (soft-DOW D).

Causal: bars in [origin, trigger) on the main TF (обычно 5m), wick near level.
tol = max(level * 1e-4, ATR14_ewm(trigger) * 0.05)
origin = htf_time - HTF length (для tf7: prev 4H open).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# Mon / Wed / Fri (UTC), pandas dayofweek: Mon=0 … Sun=6
SOFT_DOW_UTC = frozenset({0, 2, 4})
TOUCH_MIN = 5
TOL_ATR_MULT = 0.05
LEVEL_TOL_FRAC = 1e-4


def is_soft_dow(ts) -> bool:
    return int(pd.Timestamp(ts).dayofweek) in SOFT_DOW_UTC


def atr14_ewm(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev).abs(),
            (df["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()


def count_prior_touches(
    df: pd.DataFrame,
    *,
    direction: str,
    level: float,
    origin_t: pd.Timestamp,
    trigger_t: pd.Timestamp,
    atr: float,
) -> Optional[int]:
    """Число баров [origin, trigger), чья тень коснулась level ± tol."""
    if level <= 0 or trigger_t <= origin_t:
        return None
    if origin_t not in df.index:
        oi = int(df.index.searchsorted(origin_t, side="left"))
        if oi >= len(df):
            return None
        origin_t = df.index[oi]
    if trigger_t not in df.index:
        ti = int(df.index.searchsorted(trigger_t, side="right")) - 1
        if ti < 0:
            return None
        trigger_t = df.index[ti]
    oi = int(df.index.get_loc(origin_t))
    ti = int(df.index.get_loc(trigger_t))
    if isinstance(oi, slice):
        oi = oi.start
    if isinstance(ti, slice):
        ti = ti.start
    if ti <= oi:
        return None
    hist = df.iloc[oi:ti]
    if len(hist) == 0:
        return None
    atr_v = float(atr) if atr is not None and not pd.isna(atr) and atr > 0 else 0.0
    tol = max(level * LEVEL_TOL_FRAC, atr_v * TOL_ATR_MULT if atr_v > 0 else level * LEVEL_TOL_FRAC)
    highs = hist["high"].to_numpy(float)
    lows = hist["low"].to_numpy(float)
    if direction == "SHORT":
        touch = highs >= (level - tol)
    else:
        touch = lows <= (level + tol)
    return int(touch.sum())


def prior_touches_at_trigger(
    df: pd.DataFrame,
    *,
    direction: str,
    level: float,
    htf_time,
    trigger_idx: int,
    htf_minutes: int,
    atr14: Optional[pd.Series] = None,
) -> Optional[int]:
    """Удобная обёртка: origin = htf_time − htf_minutes, ATR на trigger_idx."""
    if trigger_idx < 0 or trigger_idx >= len(df) or level <= 0:
        return None
    trigger_t = pd.Timestamp(df.index[trigger_idx])
    origin_t = pd.Timestamp(htf_time) - pd.Timedelta(minutes=int(htf_minutes))
    if atr14 is None:
        atr14 = atr14_ewm(df)
    atr_v = float(atr14.iloc[trigger_idx]) if trigger_idx < len(atr14) else float("nan")
    return count_prior_touches(
        df,
        direction=direction,
        level=float(level),
        origin_t=origin_t,
        trigger_t=trigger_t,
        atr=atr_v,
    )


def need_vol_check(*, vol_enabled: bool, d_enabled: bool, soft: bool) -> bool:
    """Матрица §3: при D=ON на soft-днях vol не применяется."""
    if not vol_enabled:
        return False
    if d_enabled and soft:
        return False
    return True


def need_touches_check(*, d_enabled: bool, soft: bool) -> bool:
    return bool(d_enabled) and bool(soft)


def touches_ok(n: Optional[int], *, min_touches: int = TOUCH_MIN) -> bool:
    return n is not None and int(n) >= int(min_touches)
