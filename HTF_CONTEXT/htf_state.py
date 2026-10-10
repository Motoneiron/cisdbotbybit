# -*- coding: utf-8 -*-
"""HTF Context Engine — causal as-of машина состояний объектов (ТЗ §5).

Состояние каждого объекта на момент t считается ТОЛЬКО по барам, закрытым к t
(ни бар формирования, ни бар подтверждения, ни будущие бары в счёт не идут).

Состояния:
  FVG:   ACTIVE / PARTIALLY_FILLED / FILLED   (fill_pct = доля пройденной зоны 0..1)
  Swing: ACTIVE / SWEPT / BROKEN
         SWEPT  — фитиль вышел за уровень (high > level для SWING_HIGH), закрытий за нет;
         BROKEN — было ЗАКРЫТИЕ за уровнем (close > level).

Заморозка (frozen): как только FVG полностью заполнен / свинг пробит закрытием,
дальнейшие бары состояние не меняют — объект мёртв.

Инкрементальная реализация: advance(k) догоняет состояние до закрытого бара k
(вызывается при движении времени вперёд по отсортированным сигналам).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .htf_objects import HTFObject


class TFTracker:
    """Состояние всех объектов одного ТФ, causal as-of."""

    def __init__(self, tf: str, df: pd.DataFrame, objects: list[HTFObject]):
        self.tf = tf
        self.df = df
        self.objs = sorted(objects, key=lambda o: o.known_idx)
        self.lows = df["low"].to_numpy(dtype="float64")
        self.highs = df["high"].to_numpy(dtype="float64")
        self.closes = df["close"].to_numpy(dtype="float64")
        # состояния: на объект — None (нет просканированных баров) или dict
        self.st: list[dict | None] = [None] * len(self.objs)
        self.k = -1

    # ------------------------------------------------------------------ advance
    def advance(self, k: int) -> None:
        """Догнать состояние объектов до закрытого бара k (k монотонно растёт)."""
        if k <= self.k:
            return
        lows, highs, closes = self.lows, self.highs, self.closes
        for i, o in enumerate(self.objs):
            if o.known_idx > k:
                break  # объекты отсортированы по known_idx
            st = self.st[i]
            if st is not None and st["frozen"]:
                continue
            b0 = o.scan_start if st is None else st["b"] + 1
            if b0 > k:
                continue  # ещё нет баров для сканирования
            lo_seg = float(np.min(lows[b0:k + 1]))
            hi_seg = float(np.max(highs[b0:k + 1]))
            cl_seg_lo = float(np.min(closes[b0:k + 1]))
            cl_seg_hi = float(np.max(closes[b0:k + 1]))
            if st is None:
                st = {"b": k, "mn_lo": lo_seg, "mx_hi": hi_seg,
                      "mn_cl": cl_seg_lo, "mx_cl": cl_seg_hi, "frozen": False}
                self.st[i] = st
            else:
                if lo_seg < st["mn_lo"]:
                    st["mn_lo"] = lo_seg
                if hi_seg > st["mx_hi"]:
                    st["mx_hi"] = hi_seg
                if cl_seg_lo < st["mn_cl"]:
                    st["mn_cl"] = cl_seg_lo
                if cl_seg_hi > st["mx_cl"]:
                    st["mx_cl"] = cl_seg_hi
                st["b"] = k
            # заморозка мёртвых состояний
            if o.kind == "FVG_BULL" and st["mn_lo"] <= o.lo:
                st["frozen"] = True
            elif o.kind == "FVG_BEAR" and st["mx_hi"] >= o.hi:
                st["frozen"] = True
            elif o.kind == "SWING_HIGH" and st["mx_cl"] > o.level:
                st["frozen"] = True
            elif o.kind == "SWING_LOW" and st["mn_cl"] < o.level:
                st["frozen"] = True
        self.k = k

    # ------------------------------------------------------------- state lookup
    def obj_state(self, i: int) -> dict:
        """Состояние объекта i на текущий self.k (вызывать после advance)."""
        o = self.objs[i]
        st = self.st[i]
        if o.kind == "FVG_BULL":
            mn_lo = st["mn_lo"] if st is not None else float("inf")
            if mn_lo <= o.lo:
                return {"state": "FILLED", "fill_pct": 1.0}
            if mn_lo < o.hi:
                frac = (o.hi - mn_lo) / (o.hi - o.lo)
                return {"state": "PARTIALLY_FILLED", "fill_pct": round(min(max(frac, 0.0), 1.0), 4)}
            return {"state": "ACTIVE", "fill_pct": 0.0}
        if o.kind == "FVG_BEAR":
            mx_hi = st["mx_hi"] if st is not None else float("-inf")
            if mx_hi >= o.hi:
                return {"state": "FILLED", "fill_pct": 1.0}
            if mx_hi > o.lo:
                frac = (mx_hi - o.lo) / (o.hi - o.lo)
                return {"state": "PARTIALLY_FILLED", "fill_pct": round(min(max(frac, 0.0), 1.0), 4)}
            return {"state": "ACTIVE", "fill_pct": 0.0}
        if o.kind == "SWING_HIGH":
            mx_hi = st["mx_hi"] if st is not None else float("-inf")
            mx_cl = st["mx_cl"] if st is not None else float("-inf")
            if mx_cl > o.level:
                return {"state": "BROKEN", "fill_pct": None}
            if mx_hi > o.level:
                return {"state": "SWEPT", "fill_pct": None}
            return {"state": "ACTIVE", "fill_pct": None}
        # SWING_LOW
        mn_lo = st["mn_lo"] if st is not None else float("inf")
        mn_cl = st["mn_cl"] if st is not None else float("inf")
        if mn_cl < o.level:
            return {"state": "BROKEN", "fill_pct": None}
        if mn_lo < o.level:
            return {"state": "SWEPT", "fill_pct": None}
        return {"state": "ACTIVE", "fill_pct": None}

    # -------------------------------------------------------------- convenience
    def latest_swing(self, kind: str, k: int) -> HTFObject | None:
        """Последний подтверждённый свинг данного вида (known_idx <= k)."""
        best: HTFObject | None = None
        for o in self.objs:
            if o.known_idx > k:
                break
            if o.kind == kind:
                best = o
        return best

    def available(self, k: int):
        """Итератор (i, obj) для объектов, известных на баре k."""
        for i, o in enumerate(self.objs):
            if o.known_idx > k:
                break
            yield i, o
