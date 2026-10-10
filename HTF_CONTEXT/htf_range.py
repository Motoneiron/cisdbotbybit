# -*- coding: utf-8 -*-
"""HTF Context Engine — dealing range старших ТФ (ТЗ §8).

Диапазон = последний подтверждённый swing high ↔ последний подтверждённый swing low
(только те, что известны на момент t). range_position = (price - low) / (high - low);
> 0.5 — PREMIUM, иначе DISCOUNT. Значения не клипуются: позиция может выходить за [0,1]
(цена на новых экстремумах) — это само по себе информативно.
"""
from __future__ import annotations

from .htf_state import TFTracker


def dealing_range(tracker: TFTracker, k: int, price: float) -> dict:
    sh = tracker.latest_swing("SWING_HIGH", k)
    sl = tracker.latest_swing("SWING_LOW", k)
    if sh is None or sl is None or float(sh.level) <= float(sl.level):
        return {
            "range_low": None, "range_high": None,
            "range_position": None, "premium_discount": None,
            "swing_low_at": None, "swing_high_at": None,
        }
    lo = float(sl.level)
    hi = float(sh.level)
    pos = (float(price) - lo) / (hi - lo)
    return {
        "range_low": lo,
        "range_high": hi,
        "range_position": round(pos, 4),
        "premium_discount": "PREMIUM" if pos > 0.5 else "DISCOUNT",
        "swing_low_at": str(sl.created_at),
        "swing_high_at": str(sh.created_at),
    }
