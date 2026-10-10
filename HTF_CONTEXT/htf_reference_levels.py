# -*- coding: utf-8 -*-
"""HTF Context Engine — референс-уровни PDH/PDL/PWH/PWL (ТЗ §7, §11).

Используются ТОЛЬКО завершённые день/неделя: на момент t берётся последний
дневной (недельный) бар с close_time <= t. Незавершённая текущая свеча не участвует.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .htf_resample import TF_MINUTES


def _levels_from_frame(df: pd.DataFrame, tf: str, t: pd.Timestamp) -> dict | None:
    if df is None or len(df) == 0:
        return None
    close_ns = df.index.to_numpy(dtype="datetime64[ns]") + np.timedelta64(TF_MINUTES[tf], "m")
    tns = np.datetime64(pd.Timestamp(t))
    j = int(np.searchsorted(close_ns, tns, side="right")) - 1
    if j < 0:
        return None
    row = df.iloc[j]
    return {
        "high": float(row["high"]),
        "low": float(row["low"]),
        "bar": str(df.index[j]),
        "close": float(row["close"]),
    }


def reference_levels(df_1d: pd.DataFrame | None, df_1w: pd.DataFrame | None,
                     t: pd.Timestamp) -> dict:
    """PDH/PDL/PWH/PWL на момент t (только завершённые период)."""
    out: dict = {}
    d = _levels_from_frame(df_1d, "1D", t) if df_1d is not None else None
    w = _levels_from_frame(df_1w, "1W", t) if df_1w is not None else None
    for name, src, hi_key, lo_key in (
        ("PDH", d, "high", None), ("PDL", d, "low", None),
        ("PWH", w, "high", None), ("PWL", w, "low", None),
    ):
        if src is None:
            out[name] = None
            continue
        out[name] = {"level": float(src[hi_key if hi_key else lo_key]), "bar": src["bar"]}
    return out


def ref_distances(ref: dict, entry: float, risk: float, direction: str) -> dict:
    """Дистанции референс-уровней от entry: pct / R / выше-ниже; None если уровня нет."""
    out: dict = {}
    for name in ("PDH", "PDL", "PWH", "PWL"):
        item = ref.get(name)
        if item is None:
            out[name] = None
            continue
        lvl = float(item["level"])
        dist = lvl - entry  # >0 — выше entry, <0 — ниже
        rec = {
            "level": lvl,
            "bar": item["bar"],
            "distance_abs": dist,
            "distance_pct": round(dist / entry * 100.0, 4),
            "distance_R": round(dist / risk, 4) if risk else None,
            "side": "above" if dist > 0 else ("below" if dist < 0 else "at"),
        }
        out[name] = rec
    return out
