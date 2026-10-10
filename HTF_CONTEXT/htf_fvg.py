# -*- coding: utf-8 -*-
"""HTF Context Engine — строгий 3-свечной wick-FVG (ТЗ §3).

Bullish: low[i] > high[i-2]  → зона [high[i-2], low[i]].
Bearish: high[i] < low[i-2]  → зона [high[i], low[i-2]].
FVG становится доступен только после ЗАКРЫТИЯ свечи i (available_at = close(i)).
"""
from __future__ import annotations

import pandas as pd

from .htf_objects import HTFObject
from .htf_resample import TF_MINUTES


def detect_fvgs(df: pd.DataFrame, tf: str) -> list[HTFObject]:
    """Все FVG фрейма с causal-атрибутами (без загляда в будущее)."""
    tf_min = TF_MINUTES[tf]
    highs = df["high"].to_numpy(dtype="float64")
    lows = df["low"].to_numpy(dtype="float64")
    index = df.index
    out: list[HTFObject] = []
    n = len(df)
    for i in range(2, n):
        hi_i = float(highs[i])
        lo_i = float(lows[i])
        hi_a = float(highs[i - 2])
        lo_a = float(lows[i - 2])
        if lo_i > hi_a:
            out.append(
                HTFObject(
                    tf=tf, kind="FVG_BULL", created_idx=i, known_idx=i, scan_start=i + 1,
                    created_at=index[i],
                    available_at=index[i] + pd.Timedelta(minutes=tf_min),
                    lo=hi_a, hi=lo_i, src="fvg3",
                )
            )
        if hi_i < lo_a:
            out.append(
                HTFObject(
                    tf=tf, kind="FVG_BEAR", created_idx=i, known_idx=i, scan_start=i + 1,
                    created_at=index[i],
                    available_at=index[i] + pd.Timedelta(minutes=tf_min),
                    lo=hi_i, hi=lo_a, src="fvg3",
                )
            )
    return out
