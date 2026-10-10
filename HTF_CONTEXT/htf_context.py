# -*- coding: utf-8 -*-
"""HTF Context Engine — сборка causal-контекста на момент LTF-сигнала (ТЗ §13).

Публичный вход:
    engine = HTFContextEngine(symbol, frames)          # frames = {"4H": df, "1D": df, "1W": df}
    ctx = engine.context(decision_time, signal_dict)    # signal: direction/entry/stop/tp/cbt/tbt/htf/...

Гарантии:
  * контекст использует только бары с close_time <= decision_time (включая состояния
    объектов: fill/swept/broken считаются только по закрытым к моменту t барам);
  * исходный уровень сделки (htf_sweep_level) исключается из препятствий (ТЗ §6);
  * движок НЕ принимает торговых решений — только карта.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .htf_fvg import detect_fvgs
from .htf_path import collect_obstacles, summarize_features, MAX_PATH_R, fvg_remaining
from .htf_range import dealing_range
from .htf_reference_levels import reference_levels, ref_distances
from .htf_resample import bar_close_ns, last_closed_index
from .htf_state import TFTracker
from .htf_swings import detect_swings


class SourceExclusion:
    """Исключение исходного уровня сигнала из препятствий (ТЗ §6).

    Свип бота — это экстремум 4H-свечи (sweep_level = high/low конкретного 4H-бара),
    поэтому матчинг строгий: исключаются только объекты ТФ «4H», чей уровень (свинг) или
    граница зоны (FVG) ТОЧНО совпадают со свипнутым уровнем (допуск 2 bps).

    Широкий матчинг «зона содержит уровень» НЕ используется: на дымовом прогоне ADA он
    вырезал десятки старых зон (их диапазоны просто накрывали цену свипа) и заметно
    искажал карту. Исключать нужно конкретный объект-источник, а не всё, что совпало по цене.
    """

    def __init__(self, level: float | None, tol_rel: float = 0.0002, tf: str = "4H"):
        self.level = float(level) if level else None
        self.tol_rel = float(tol_rel)
        self.tf = tf
        self.hits: list[dict] = []

    def disabled(self, o) -> bool:
        if self.level is None or o.tf != self.tf:
            return False
        tol = abs(self.level) * self.tol_rel
        if o.is_fvg():
            hit = abs(float(o.lo) - self.level) <= tol or abs(float(o.hi) - self.level) <= tol
        else:
            hit = abs(float(o.level) - self.level) <= tol
        if hit:
            self.hits.append(o.to_dict())
        return hit


def _map_lists(tr: TFTracker, k: int, entry: float, fvg_cap: int = 3, swing_cap: int = 2) -> dict:
    """Списки ближайших FVG/свингов выше/ниже entry (включая straddle), без учёта exclusion."""
    fvg_above: list[dict] = []
    fvg_below: list[dict] = []
    swing_above: list[dict] = []
    swing_below: list[dict] = []
    for i, o in tr.available(k):
        st = tr.obj_state(i)
        if o.is_fvg():
            if st["state"] == "FILLED":
                continue
            r_lo, r_hi = fvg_remaining(o, st)
            if r_lo >= entry:
                side, dist = "above", r_lo - entry
            elif r_hi <= entry:
                side, dist = "below", entry - r_hi
            else:
                side, dist = "straddle", 0.0
            rec = {
                "lo": round(float(o.lo), 10), "hi": round(float(o.hi), 10),
                "rem_lo": round(r_lo, 10), "rem_hi": round(r_hi, 10),
                "state": st["state"], "fill_pct": st["fill_pct"],
                "side": side, "distance_abs": round(dist, 10),
                "distance_pct": round(dist / entry * 100.0, 4),
                "signed_distance_pct": round((dist if side == "above" else -dist) / entry * 100.0, 4)
                if side != "straddle" else 0.0,
            }
            (fvg_above if side == "above" else fvg_below if side == "below" else fvg_above).append(rec)
        else:
            if st["state"] != "ACTIVE":
                continue
            lvl = float(o.level)
            if lvl > entry:
                side, dist = "above", lvl - entry
            elif lvl < entry:
                side, dist = "below", entry - lvl
            else:
                side, dist = "at", 0.0
            rec = {
                "level": round(lvl, 10), "state": st["state"], "side": side,
                "distance_abs": round(dist, 10),
                "distance_pct": round(dist / entry * 100.0, 4),
                "signed_distance_pct": round((dist if side == "above" else -dist) / entry * 100.0, 4)
                if side != "at" else 0.0,
            }
            (swing_above if side in ("above", "at") else swing_below).append(rec)
    for lst, cap in ((fvg_above, fvg_cap), (fvg_below, fvg_cap), (swing_above, swing_cap), (swing_below, swing_cap)):
        lst.sort(key=lambda r: r["distance_abs"])
        del lst[cap:]
    return {"fvg_above": fvg_above, "fvg_below": fvg_below,
            "swing_above": swing_above, "swing_below": swing_below}


class HTFContextEngine:
    """Движок HTF-карты по одному символу: объекты 4H/1D/1W + causal as-of состояние."""

    def __init__(self, symbol: str, frames: dict[str, pd.DataFrame]):
        self.symbol = symbol
        self.frames = frames
        self.trackers: dict[str, TFTracker] = {}
        for tf, df in frames.items():
            if df is None or len(df) == 0:
                continue
            objs = detect_fvgs(df, tf) + detect_swings(df, tf)
            self.trackers[tf] = TFTracker(tf, df, objs)
        self.close_ns: dict[str, np.ndarray] = {
            tf: bar_close_ns(df, tf) for tf, df in frames.items() if df is not None and len(df)
        }

    # --------------------------------------------------------------- internals
    def _ks(self, t: pd.Timestamp) -> dict[str, int]:
        ks: dict[str, int] = {}
        for tf, tr in self.trackers.items():
            k = last_closed_index(self.close_ns[tf], t)
            tr.advance(k)
            ks[tf] = k
        return ks

    def objects_snapshot(self, t, only_kind: str | None = None) -> list[dict]:
        """Диагностика: все известные объекты с состоянием на момент t (для тестов)."""
        ks = self._ks(pd.Timestamp(t))
        out = []
        for tf, tr in self.trackers.items():
            k = ks.get(tf, -1)
            if k < 0:
                continue
            for i, o in tr.available(k):
                if only_kind and o.kind != only_kind:
                    continue
                rec = o.to_dict()
                rec.update(tr.obj_state(i))
                out.append(rec)
        return out

    # ------------------------------------------------------------------ public
    def context(self, decision_time, signal: dict, tp_r: float = 1.0, px: float | None = None) -> dict:
        """Causal HTF-контекст на момент decision_time (только закрытые данные)."""
        t = pd.Timestamp(decision_time)
        ks = self._ks(t)

        entry = float(signal["entry"])
        stop = float(signal.get("stop") or 0.0)
        direction = str(signal["direction"])
        risk = abs(entry - stop)
        px = float(px if px is not None else entry)

        # исключение исходного уровня сигнала (§6)
        exclusion = SourceExclusion(signal.get("htf_sweep_level"))

        # референс-уровни (завершённые день/неделя)
        refs_raw = reference_levels(self.frames.get("1D"), self.frames.get("1W"), t)
        refs = ref_distances(refs_raw, entry, risk, direction)

        obstacles = collect_obstacles(self.trackers, ks, entry, direction, risk, refs, exclusion)
        summary = summarize_features(obstacles, tp_r=tp_r)

        # блоки по ТФ: range + ближайшие + списки карты
        htf_blocks: dict = {}
        for tf in ("4H", "1D", "1W"):
            tr = self.trackers.get(tf)
            k = ks.get(tf, -1)
            block: dict = {"range_low": None, "range_high": None, "range_position": None,
                           "premium_discount": None}
            if tr is not None and k >= 0:
                block.update({k2: v for k2, v in dealing_range(tr, k, px).items()
                              if k2 in ("range_low", "range_high", "range_position", "premium_discount")})
                block.update({
                    "nearest_obstacle_R": summary.get(f"nearest_{tf.lower()}_obstacle_R"),
                    "nearest_fvg_R": summary.get(f"nearest_{tf.lower()}_fvg_R"),
                    "nearest_swing_R": summary.get(f"nearest_{tf.lower()}_swing_R"),
                })
                block.update(_map_lists(tr, k, entry))
            htf_blocks[tf] = block

        out = {
            "symbol": self.symbol,
            "decision_time": str(t),
            "signal": {
                "tf": "15m",
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": signal.get("tp"),
                "risk_pct": round(abs(entry - stop) / entry * 100.0, 4) if entry else None,
                "px": px,
                "cbt": signal.get("cbt"),
                "tbt": signal.get("tbt"),
                "htf": signal.get("htf"),
                "scan": signal.get("scan"),
                "cisd_level": signal.get("cisd_level"),
                "htf_sweep_level": signal.get("htf_sweep_level"),
            },
            "htf": htf_blocks,
            "reference": refs,
            "path": obstacles,
            "summary": summary,
            "excluded_sources": exclusion.hits,
        }
        return out
