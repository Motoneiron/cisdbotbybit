# -*- coding: utf-8 -*-
"""Точечный пересчёт 3 сигналов: фитиль 4H и ближайший уровень со стороны стопа."""
import glob
import importlib.util
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")

from HTF_CONTEXT.htf_context import HTFContextEngine
from HTF_CONTEXT.htf_resample import load_1m, make_frames
from HTF_CONTEXT.research_htf_context import PATHS, PREHISTORY, UNTIL

spec = importlib.util.spec_from_file_location("wkm", r"D:\PYTHON\cisdbotbybit\RUNS\temp\_htf_wick_level.py")
wkm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wkm)

WKC = r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_wick_level.csv"
NF_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter"

wk = pd.read_csv(WKC)
samples = [
    ("SOL", "стоп за уровнем"),
    ("LINK", "уровень не взят"),
    ("BTC", "фитиль наколол, стоп перед уровнем"),
]
chosen = []
for sym, grp in samples:
    sub = wk[(wk.symbol == sym) & (wk.grp == grp)]
    if len(sub):
        chosen.append(sub.iloc[0])
chosen.append(wk[(wk.symbol == "ADA") & (wk.lvl_type == "FVG_BEAR") & (wk.grp == "стоп за уровнем")].iloc[0])
chosen.append(wk[(wk.symbol == "DOGE") & (wk.lvl_type == "PDL")].iloc[0] if len(wk[(wk.symbol=="DOGE") & (wk.lvl_type=="PDL")]) else None)
chosen = [c for c in chosen if c is not None]

for c in chosen:
    sym = c.symbol
    files = glob.glob(os.path.join(NF_DIR, f"{sym}_*.pkl"))
    rows = []
    for f in files:
        rows += pickle.load(open(f, "rb"))
    m = [r for r in rows if str(r["scan"]) == str(c.scan) and r["direction"] == c.direction]
    if not m:
        print(f"[{sym} {c.scan}] НЕ НАЙДЕНО в nofilter pkl!"); continue
    r = m[0]
    df1 = load_1m(PATHS[sym], PREHISTORY, UNTIL)
    frames = make_frames(df1)
    eng = HTFContextEngine(sym, frames)
    idx = df1.index.to_numpy(dtype="datetime64[ns]")
    hi = df1["high"].to_numpy(dtype="float64")
    lo = df1["low"].to_numpy(dtype="float64")
    tbt = r.get("tbt") or r.get("cbt") or r.get("scan")
    h4 = wkm.h4_open_of(tbt)
    w = wkm.wick_until(idx, hi, lo, h4, r["scan"])
    lvl = wkm.nearest_stop_side(eng, h4, float(r["entry"]), r["direction"])
    grp2 = wkm.classify(r["direction"], float(r["entry"]), float(r["stop"]), w[0], w[1], lvl)
    near = None if lvl is None else lvl["near"]
    pct2 = None if near is None else abs(near - float(r["entry"])) / float(r["entry"]) * 100.0
    print(f"\n=== {sym} {c.scan} {c.direction} ===")
    print(f"  tbt={tbt} scan={r['scan']} 4H_open={h4}")
    print(f"  entry={r['entry']:.6g} stop={r['stop']:.6g} trigger_extreme={r['trigger_extreme']:.6g} sweep={r.get('htf_sweep_level')}")
    print(f"  CSV : grp={c.grp:38s} lvl={c.lvl_type}({c.lvl_tf}) pct={c.lvl_pct:.3f} wick_hi={c.wick_hi:.6g} wick_lo={c.wick_lo:.6g}")
    print(f"  REC : grp={grp2:38s} lvl={None if lvl is None else lvl['type']}({None if lvl is None else lvl['tf']}) "
          f"pct={None if pct2 is None else round(pct2,3)} wick_hi={w[0]:.6g} wick_lo={w[1]:.6g}")
    ok = (grp2 == c.grp) and (abs(w[0] - c.wick_hi) < 1e-6) and (abs(w[1] - c.wick_lo) < 1e-6)
    print(f"  MATCH: {ok}")
