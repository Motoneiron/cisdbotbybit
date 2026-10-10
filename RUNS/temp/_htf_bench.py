# -*- coding: utf-8 -*-
"""Bench: сколько стоит один context() и сборка движка на полных данных ADA."""
import sys, os, time
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
import pandas as pd
from HTF_CONTEXT.htf_resample import load_1m, make_frames, bar_close_ns, last_closed_index
from HTF_CONTEXT.htf_context import HTFContextEngine

t0 = time.time()
df1 = load_1m(r"D:\databtcusdt\ADAUSDT-1m-merged.csv", "2022-01-01", "2026-09-02")
print(f"load_1m: {time.time()-t0:.1f}s, bars={len(df1):,}")
t0 = time.time()
frames = make_frames(df1)
print(f"frames: {time.time()-t0:.1f}s; 4H={len(frames['4H']):,} 1D={len(frames['1D']):,} 1W={len(frames['1W']):,}")
t0 = time.time()
eng = HTFContextEngine("ADA", frames)
nobjs = sum(len(tr.objs) for tr in eng.trackers.values())
print(f"engine build: {time.time()-t0:.1f}s; objects={nobjs}")

close_ns = {tf: bar_close_ns(df, tf) for tf, df in frames.items()}
times = [str(t) for t in pd.date_range("2024-01-02", "2026-08-25", freq="20D")]
print(f"contexts to bench: {len(times)}")
t0 = time.time()
k4 = 0
for i, t in enumerate(times):
    ks = {tf: last_closed_index(close_ns[tf], t) for tf in frames}
    if ks["4H"] < 0:
        continue
    entry = float(frames["4H"]["close"].iloc[ks["4H"]])
    sig = {"direction": "LONG" if i % 2 == 0 else "SHORT", "entry": entry,
           "stop": entry * (0.985 if i % 2 == 0 else 1.015),
           "tp": entry * (1.015 if i % 2 == 0 else 0.985),
           "htf_sweep_level": float(frames["4H"]["low"].iloc[ks["4H"]]),
           "scan": t}
    eng.context(t, sig, px=entry)
dt = time.time() - t0
print(f"context loop: {dt:.1f}s for {len(times)} → {dt/len(times)*1000:.1f} ms/context")
