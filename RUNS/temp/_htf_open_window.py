# -*- coding: utf-8 -*-
"""Ближайший и следующий HTF-уровень БЕЗ потолка 5R.

Сначала уровень (FVG / свинг / PDH/PDL/PWH/PWL), потом дистанция:
  * в процентах цены
  * в стопах (та же дистанция / ширина стопа)

Окно не режется. Уровень, который дальше 5 стопов, остаётся в карте.
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

from HTF_CONTEXT.htf_context import HTFContextEngine, SourceExclusion
from HTF_CONTEXT.htf_path import _is_dead, _obj_side_dist
from HTF_CONTEXT.htf_reference_levels import ref_distances, reference_levels
from HTF_CONTEXT.htf_resample import load_1m, make_frames
from HTF_CONTEXT.research_htf_context import PATHS, PREHISTORY, UNTIL, PAIRS10

NF_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter"


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

OUT_CSV = r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_open_window.csv"
OUT_MD = r"D:\PYTHON\cisdbotbybit\RUNS\HTF_OPEN_WINDOW_2026-10-10.md"

PCT_EDGES = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0]
PCT_LABELS = ["<0.5%", "0.5-1%", "1-2%", "2-3%", "3-5%", "5-8%", ">8%"]


def pct_bucket(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "нет уровня"
    x = float(v)
    for edge, name in zip(PCT_EDGES, PCT_LABELS):
        if x < edge:
            return name
    return PCT_LABELS[-1]


def two_ahead(eng: HTFContextEngine, t, signal: dict) -> list[dict]:
    """Два ближайших живых объекта по пути сделки. Без потолка в R."""
    ks = eng._ks(pd.Timestamp(t))
    entry = float(signal["entry"])
    stop = float(signal.get("stop") or 0.0)
    direction = str(signal["direction"])
    risk = abs(entry - stop)
    exclusion = SourceExclusion(signal.get("htf_sweep_level"))
    refs = ref_distances(
        reference_levels(eng.frames.get("1D"), eng.frames.get("1W"), pd.Timestamp(t)),
        entry, risk, direction,
    )
    found: list[tuple[float, dict]] = []
    for tf in ("4H", "1D", "1W"):
        tr = eng.trackers.get(tf)
        if tr is None:
            continue
        k = ks.get(tf, -1)
        if k < 0:
            continue
        for i, o in tr.available(k):
            if exclusion.disabled(o):
                continue
            st = tr.obj_state(i)
            if _is_dead(o, st):
                continue
            sd = _obj_side_dist(o, st, entry, direction)
            if sd is None:
                continue
            _side, dist = sd
            found.append((dist, {
                "tf": tf, "type": o.kind,
                "pct": dist / entry * 100.0 if entry else None,
                "R": dist / risk if risk else None,
            }))
    want = "above" if direction == "LONG" else "below"
    for name, tf in (("PDH", "1D"), ("PDL", "1D"), ("PWH", "1W"), ("PWL", "1W")):
        item = refs.get(name)
        if item is None or item["side"] != want:
            continue
        dist = abs(float(item["distance_abs"]))
        found.append((dist, {
            "tf": tf, "type": name,
            "pct": dist / entry * 100.0 if entry else None,
            "R": dist / risk if risk else None,
        }))
    found.sort(key=lambda x: x[0])
    return [rec for _d, rec in found[:2]]


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
        print(f"[{sym}] 1m={len(df1):,} сигналов={len(rs)} загрузка {time.time()-t1:.0f}s", flush=True)
        for r in rs:
            q = r.get("r") if r.get("taken") else r.get("r_cf")
            if q is None or (isinstance(q, float) and np.isnan(q)):
                continue
            top = two_ahead(eng, r["scan"], r)
            n1 = top[0] if len(top) > 0 else {}
            n2 = top[1] if len(top) > 1 else {}
            rows_out.append({
                "symbol": sym, "scan": r.get("scan"), "direction": r.get("direction"),
                "taken": bool(r.get("taken")), "gate_rej": bool(r.get("gate_rej")),
                "ms_rej": bool(r.get("ms_rej")), "dt_rej": bool(r.get("dt_rej")),
                "sweep_rej": bool(r.get("sweep_rej")),
                "outcome": r.get("outcome") if r.get("taken") else r.get("outcome_cf"),
                "q": float(q), "sp": r.get("sp"),
                "n1_pct": n1.get("pct"), "n1_R": n1.get("R"),
                "n1_type": n1.get("type"), "n1_tf": n1.get("tf"),
                "n2_pct": n2.get("pct"), "n2_R": n2.get("R"),
                "n2_type": n2.get("type"), "n2_tf": n2.get("tf"),
            })
            n_done += 1
            if n_done % 500 == 0:
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


def bucket_table(df: pd.DataFrame, col: str) -> str:
    df = df.copy()
    df["_b"] = df[col].map(pct_bucket)
    rows = []
    for name in PCT_LABELS + ["нет уровня"]:
        g = df[df["_b"] == name]
        if len(g) == 0:
            continue
        sp = g["sp"].median()
        rr = g[col.replace("_pct", "_R")].median() if col.endswith("_pct") else None
        extra = f"{sp * 100:.2f}%" if pd.notna(sp) else "—"
        rmed = f"{rr:.2f}" if rr is not None and pd.notna(rr) else "—"
        rows.append([name, stat(g), extra, rmed])
    return md(["корзина", "n / WR / avgR / CI95", "медиана стопа", "медиана R до этого уровня"], rows)


def report(df: pd.DataFrame) -> None:
    taken = df[df["taken"]].copy()
    passed = df[~df["gate_rej"]].copy()
    cut = df[df["gate_rej"]].copy()
    L = []
    L.append("# Ближайший уровень без потолка 5R (10.10.2026)")
    L.append("")
    L.append("Окно не режется стопами. Сначала находится живой уровень по пути сделки "
             "(FVG, свинг, PDH/PDL/PWH/PWL), потом считается дистанция в % цены и в стопах.")
    L.append(f"Сигналов с исходом: {len(df)}. Взятых без фильтров: {len(taken)}. "
             f"Гейт пропускал: {len(passed)}. Гейт отсёк: {len(cut)}.")
    miss = int(df["n1_pct"].isna().sum())
    L.append(f"Без единого уровня впереди: {miss} из {len(df)}.")
    L.append("")
    L.append(f"Ближайший уровень, медиана дистанции: {df['n1_pct'].median():.2f}% цены, "
             f"{df['n1_R'].median():.2f} стопа. Следующий: {df['n2_pct'].median():.2f}% / {df['n2_R'].median():.2f}R.")
    L.append("")
    L.append("Дальше 5 стопов (старая карта писала «пусто»): "
             f"{int((df['n1_R'] > 5).sum())} сигналов, { (df['n1_R'] > 5).mean() * 100:.1f}%.")
    L.append("")
    L.append("## 1. Взятые сделки без фильтров — ближайший уровень, % цены")
    L.append("")
    L.append(bucket_table(taken, "n1_pct"))
    L.append("")
    L.append("## 2. То же — следующий уровень")
    L.append("")
    L.append(bucket_table(taken, "n2_pct"))
    L.append("")
    L.append("## 3. Гейт пропускал — ближайший, % цены")
    L.append("")
    L.append(bucket_table(passed, "n1_pct"))
    L.append("")
    L.append("## 4. Гейт отсёк — ближайший, % цены")
    L.append("")
    L.append(bucket_table(cut, "n1_pct"))
    L.append("")
    L.append("## 5. Кто стоит ближайшим (взятые)")
    L.append("")
    vc = taken["n1_type"].fillna("нет").value_counts()
    rows = []
    for name, n in vc.items():
        g = taken[taken["n1_type"].fillna("нет") == name]
        rows.append([name, stat(g), f"{g['n1_pct'].median():.2f}%"])
    L.append(md(["тип", "n / WR / avgR / CI95", "медиана дистанции"], rows))
    L.append("")
    text = "\n".join(L) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


def main() -> None:
    if os.path.exists(OUT_CSV) and "--rebuild" not in sys.argv:
        df = pd.read_csv(OUT_CSV)
        print("читаю готовый", OUT_CSV, len(df), flush=True)
    else:
        df = build()
    report(df)


if __name__ == "__main__":
    main()
