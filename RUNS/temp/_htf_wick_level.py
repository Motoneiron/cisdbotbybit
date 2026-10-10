# -*- coding: utf-8 -*-
"""Фитиль 4H-свечи, в которой сидит триггер: наколол ли ближайший уровень со стороны стопа,
и стоит ли стоп за этим уровнем.

Уровень известен до открытия этой 4H-свечи. Фитиль — только до момента решения (scan),
без хвоста незакрытой свечи.
"""
from __future__ import annotations

import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")

from HTF_CONTEXT.htf_context import HTFContextEngine
from HTF_CONTEXT.htf_path import _is_dead, fvg_remaining
from HTF_CONTEXT.htf_reference_levels import reference_levels
from HTF_CONTEXT.htf_resample import load_1m, make_frames
from HTF_CONTEXT.research_htf_context import PAIRS10, PATHS, PREHISTORY, UNTIL

NF_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter"
OUT_CSV = r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_wick_level.csv"
OUT_MD = r"D:\PYTHON\cisdbotbybit\RUNS\HTF_WICK_LEVEL_2026-10-10.md"


def load_rows(d: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in sorted(glob.glob(os.path.join(d, "*.pkl"))):
        sym = os.path.basename(f).rsplit("_", 1)[0]
        if sym not in PAIRS10:
            continue
        out.setdefault(sym, []).extend(pickle.load(open(f, "rb")))
    for s in out:
        out[s].sort(key=lambda r: str(r.get("scan") or ""))
    return out


def h4_open_of(tbt) -> pd.Timestamp:
    t = pd.Timestamp(tbt)
    return t.floor("4h")


def wick_until(idx_ns, highs, lows, h4_open, scan) -> tuple[float, float] | None:
    """Максимум/минимум 1m от открытия 4H до scan (свечи, уже закрытые к решению)."""
    a = np.datetime64(pd.Timestamp(h4_open))
    b = np.datetime64(pd.Timestamp(scan))
    i0 = int(np.searchsorted(idx_ns, a, side="left"))
    i1 = int(np.searchsorted(idx_ns, b, side="left"))
    if i1 <= i0:
        return None
    return float(np.max(highs[i0:i1])), float(np.min(lows[i0:i1]))


def nearest_stop_side(eng: HTFContextEngine, h4_open, entry: float, direction: str) -> dict | None:
    """Ближайший живой уровень со стороны стопа, известный до открытия 4H-свечи."""
    ks = eng._ks(pd.Timestamp(h4_open))
    refs = reference_levels(eng.frames.get("1D"), eng.frames.get("1W"), pd.Timestamp(h4_open))
    best = None
    best_dist = None

    def consider(price_near: float, price_far: float, typ: str, tf: str):
        nonlocal best, best_dist
        if direction == "LONG":
            if not price_near < entry:
                return
            dist = entry - price_near
        else:
            if not price_near > entry:
                return
            dist = price_near - entry
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = {"near": float(price_near), "far": float(price_far), "type": typ, "tf": tf}

    for tf in ("4H", "1D", "1W"):
        tr = eng.trackers.get(tf)
        if tr is None:
            continue
        k = ks.get(tf, -1)
        if k < 0:
            continue
        for i, o in tr.available(k):
            st = tr.obj_state(i)
            if _is_dead(o, st):
                continue
            if o.is_fvg():
                lo, hi = fvg_remaining(o, st)
                # ближний к цене край зоны со стороны стопа
                if direction == "LONG" and o.kind == "FVG_BULL":
                    consider(hi, lo, o.kind, tf)
                elif direction == "SHORT" and o.kind == "FVG_BEAR":
                    consider(lo, hi, o.kind, tf)
            elif direction == "LONG" and o.kind == "SWING_LOW":
                consider(float(o.level), float(o.level), o.kind, tf)
            elif direction == "SHORT" and o.kind == "SWING_HIGH":
                consider(float(o.level), float(o.level), o.kind, tf)
    # референсы: для лонга снизу PDL/PWL, для шорта сверху PDH/PWH
    if direction == "LONG":
        for name in ("PDL", "PWL"):
            item = refs.get(name)
            if item:
                consider(float(item["level"]), float(item["level"]), name, "1D" if name == "PDL" else "1W")
    else:
        for name in ("PDH", "PWH"):
            item = refs.get(name)
            if item:
                consider(float(item["level"]), float(item["level"]), name, "1D" if name == "PDH" else "1W")
    return best


def classify(direction: str, entry: float, stop: float, wick_hi: float, wick_lo: float, lvl: dict | None) -> str:
    if lvl is None:
        return "нет уровня"
    near = lvl["near"]
    if direction == "LONG":
        pierced = wick_lo <= near
        stop_behind = stop < near
    else:
        pierced = wick_hi >= near
        stop_behind = stop > near
    if stop_behind:
        return "стоп за уровнем"
    if pierced:
        return "фитиль наколол, стоп перед уровнем"
    return "уровень не взят"


def build() -> pd.DataFrame:
    nf = load_rows(NF_DIR)
    rows_out = []
    t0 = time.time()
    n_done = 0
    for sym in PAIRS10:
        rs = nf.get(sym) or []
        if not rs or not os.path.exists(PATHS[sym]):
            print(f"[{sym}] пропуск", flush=True)
            continue
        t1 = time.time()
        df1 = load_1m(PATHS[sym], PREHISTORY, UNTIL)
        frames = make_frames(df1)
        eng = HTFContextEngine(sym, frames)
        idx_ns = df1.index.to_numpy(dtype="datetime64[ns]")
        highs = df1["high"].to_numpy(dtype="float64")
        lows = df1["low"].to_numpy(dtype="float64")
        print(f"[{sym}] 1m={len(df1):,} сигналов={len(rs)} загрузка {time.time()-t1:.0f}s", flush=True)
        for r in rs:
            q = r.get("r") if r.get("taken") else r.get("r_cf")
            if q is None or (isinstance(q, float) and np.isnan(q)):
                continue
            tbt = r.get("tbt") or r.get("cbt") or r.get("scan")
            h4 = h4_open_of(tbt)
            w = wick_until(idx_ns, highs, lows, h4, r["scan"])
            if w is None:
                continue
            wh, wl = w
            lvl = nearest_stop_side(eng, h4, float(r["entry"]), r["direction"])
            grp = classify(r["direction"], float(r["entry"]), float(r["stop"]), wh, wl, lvl)
            near = None if lvl is None else lvl["near"]
            pct = None if near is None else abs(near - float(r["entry"])) / float(r["entry"]) * 100.0
            rows_out.append({
                "symbol": sym, "scan": r.get("scan"), "direction": r.get("direction"),
                "taken": bool(r.get("taken")),
                "gate_rej": bool(r.get("gate_rej")), "ms_rej": bool(r.get("ms_rej")),
                "dt_rej": bool(r.get("dt_rej")), "sweep_rej": bool(r.get("sweep_rej")),
                "outcome": r.get("outcome") if r.get("taken") else r.get("outcome_cf"),
                "q": float(q), "sp": r.get("sp"),
                "entry": float(r["entry"]), "stop": float(r["stop"]),
                "grp": grp,
                "lvl_type": None if lvl is None else lvl["type"],
                "lvl_tf": None if lvl is None else lvl["tf"],
                "lvl_pct": pct,
                "wick_hi": wh, "wick_lo": wl,
            })
            n_done += 1
            if n_done % 2000 == 0:
                print(f"  ... {n_done}  {time.time()-t0:.0f}s", flush=True)
        print(f"[{sym}] готово, всего {n_done}, {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows_out)
    df.to_csv(OUT_CSV, index=False)
    print("CSV", OUT_CSV, len(df), flush=True)
    return df


def stat(g: pd.DataFrame) -> str:
    n = len(g)
    if n == 0:
        return "—"
    q = g["q"].astype(float)
    tp = int((g["outcome"] == "tp").sum())
    sd = float(q.std(ddof=1)) if n > 1 else 0.0
    half = 1.96 * sd / np.sqrt(n) if n > 1 else 0.0
    m = float(q.mean())
    return f"{n} / {tp / n * 100:.1f}% / {m:+.3f} / [{m - half:+.3f},{m + half:+.3f}]"


def md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


ORDER = [
    "стоп за уровнем",
    "фитиль наколол, стоп перед уровнем",
    "уровень не взят",
    "нет уровня",
]


def block(title: str, df: pd.DataFrame) -> list[str]:
    L = [f"## {title}", ""]
    rows = []
    for name in ORDER:
        g = df[df["grp"] == name]
        if len(g) == 0:
            rows.append([name, "—", "—"])
            continue
        med = g["lvl_pct"].median()
        med_s = f"{med:.2f}%" if pd.notna(med) else "—"
        rows.append([name, stat(g), med_s])
    L.append(md(["группа", "n / WR / avgR / CI95", "медиана дистанции до уровня"], rows))
    L.append("")
    return L


def report(df: pd.DataFrame) -> None:
    passed = df[~df["gate_rej"] & ~df["ms_rej"] & ~df["dt_rej"] & ~df["sweep_rej"]]
    taken_live = passed[passed["taken"]]
    taken_nf = df[df["taken"]]
    L = []
    L.append("# Фитиль 4H и ближайший уровень со стороны стопа (10.10.2026)")
    L.append("")
    L.append("Ближайший живой уровень ниже входа для лонга и выше входа для шорта "
             "(свинг, FVG с этой стороны, PDH/PDL/PWH/PWL). Уровень уже существовал до открытия "
             "той 4H-свечи, внутри которой сидит триггер. Фитиль этой свечи взят только до момента решения.")
    L.append("Стоп в этих сигналах всегда равен экстремуму триггер-бара. "
             "«Стоп за уровнем» значит: уровень лежит между входом и стопом, фитиль до него дошёл. "
             "«Фитиль наколол, стоп перед уровнем» — 4H-свеча дошла до уровня дальше, чем наш стоп. "
             "«Уровень не взят» — фитиль до ближайшего уровня не дошёл.")
    L.append(f"Сигналов с исходом: {len(df)}. Взятых по живому отбору: {len(taken_live)}. "
             f"Взятых без фильтров: {len(taken_nf)}.")
    L.append("")
    L.extend(block("1. Живой отбор, взятые сделки", taken_live))
    L.extend(block("2. Без фильтров, взятые сделки", taken_nf))
    L.extend(block("3. Все сигналы с исходом (контрфакт, если не взяли)", df))
    L.append("## 4. Тип ближайшего уровня (взятые без фильтров)")
    L.append("")
    rows = []
    sub = taken_nf.copy()
    for typ, g in sub.groupby(sub["lvl_type"].fillna("нет")):
        rows.append([typ, len(g), f"{g['lvl_pct'].median():.2f}%" if g["lvl_pct"].notna().any() else "—", stat(g)])
    rows.sort(key=lambda r: -int(r[1]) if str(r[1]).isdigit() else 0)
    L.append(md(["тип", "n", "медиана дистанции", "n / WR / avgR / CI95"], rows))
    L.append("")
    text = "\n".join(L) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


def main() -> None:
    if os.path.exists(OUT_CSV) and "--rebuild" not in sys.argv:
        df = pd.read_csv(OUT_CSV)
    else:
        df = build()
    report(df)


if __name__ == "__main__":
    main()
