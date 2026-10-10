# -*- coding: utf-8 -*-
"""HTF Context Engine — подтверждённый 3-свечной свинг (ТЗ §4).

Swing high: high[i] > high[i-1] и high[i] >= high[i+1].
Swing low:  low[i]  < low[i-1]  и low[i]  <= low[i+1].
Свинг известен только после ЗАКРЫТИЯ правой свечи i+1
(available_at = close(i+1)); состояние сканируется с бара i+2.
"""
from __future__ import annotations

import pandas as pd

from .htf_objects import HTFObject
from .htf_resample import TF_MINUTES


def detect_swings(df: pd.DataFrame, tf: str) -> list[HTFObject]:
    """Все подтверждённые свинги фрейма с causal-атрибутами."""
    tf_min = TF_MINUTES[tf]
    highs = df["high"].to_numpy(dtype="float64")
    lows = df["low"].to_numpy(dtype="float64")
    index = df.index
    out: list[HTFObject] = []
    n = len(df)
    for i in range(1, n - 1):
        if highs[i] > highs[i - 1] and highs[i] >= highs[i + 1]:
            out.append(
                HTFObject(
                    tf=tf, kind="SWING_HIGH", created_idx=i, known_idx=i + 1, scan_start=i + 2,
                    created_at=index[i],
                    available_at=index[i + 1] + pd.Timedelta(minutes=tf_min),
                    level=float(highs[i]), src="swing3",
                )
            )
        if lows[i] < lows[i - 1] and lows[i] <= lows[i + 1]:
            out.append(
                HTFObject(
                    tf=tf, kind="SWING_LOW", created_idx=i, known_idx=i + 1, scan_start=i + 2,
                    created_at=index[i],
                    available_at=index[i + 1] + pd.Timedelta(minutes=tf_min),
                    level=float(lows[i]), src="swing3",
                )
            )
    return out
