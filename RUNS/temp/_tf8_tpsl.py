"""tf8-only: TP/SL/TIME + WR по вариантам (сигнальный уровень), по годам и 2024-26."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
tp_ = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
kk = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = kk(df); tp_["k"] = kk(tp_)
mp = dict(zip(tp_.k, tp_["r_1_0"]))
df["r"] = [mp.get(x) for x in df.k]
df = df[df.r.notna()].copy()
df["ts_fill"] = pd.to_datetime(df.ts_fill); df["exit_ts"] = pd.to_datetime(df.exit_ts)
df = df[df.prof == "tf8"].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1; V = df.vd_conf
E3 = ((L & (s > 0.0002)) | (S & (s < -0.0002))).fillna(False)
G = ((S & (V <= 0)) | (L & (V >= 0))).fillna(False)
MS = df.sp >= 0.005
VAR = [("без фильтров", pd.Series(True, index=df.index)), ("+ min_stop 0.5%", MS),
       ("+ vwap-гейт", G & MS), ("+ EMA3 1H", E3 & MS), ("+ vwap + EMA3", G & E3 & MS)]


def row(g, days):
    t = g[g.outcome == "tp"]; sl = g[g.outcome == "sl"]; tm = g[g.outcome == "time"]
    wr = 100.0 * len(t) / max(len(t) + len(sl), 1)
    return (len(g), len(t), len(sl), len(tm), wr, g.r.sum(), g.r.mean(), len(g) / days)


def table(sub, days, header):
    print(header)
    print(f"  {'вариант':17} | {'сделок':>7} {'/день':>6} | {'TP':>6} {'SL':>6} {'TIME':>6} | {'WR':>6} | {'ΣR':>9} {'avg':>8} | {'ΣR(TP)':>8} {'ΣR(SL)':>8} {'ΣR(TIME)':>9}")
    for lab, m in VAR:
        g = sub[m.loc[sub.index]]
        n, nt, ns, nm, wr, sr, av, per = row(g, days)
        sr_t = g[g.outcome == "tp"].r.sum(); sr_s = g[g.outcome == "sl"].r.sum(); sr_m = g[g.outcome == "time"].r.sum()
        print(f"  {lab:17} | {n:7d} {per:6.2f} | {nt:6d} {ns:6d} {nm:6d} | {wr:5.1f}% | {sr:+9.1f} {av:+8.4f} | {sr_t:+8.1f} {sr_s:+8.1f} {sr_m:+9.1f}")
    print()


days_all = (df.exit_ts.max() - df.ts_fill.min()).days
table(df, days_all, f"===== tf8-only, ВСЕ ГОДЫ (2020-01-01..2026-09-06, {days_all} дней) =====")
d24 = df[df.year >= 2024].copy()
table(d24, (d24.exit_ts.max() - d24.ts_fill.min()).days, f"===== tf8-only, 2024-26 ({d24.exit_ts.max()-d24.ts_fill.min()}:  дней) =====")

print("===== tf8-only по годам (WR и исходы) =====")
for lab, m in VAR:
    print(f"\n  -- {lab} --")
    for y in sorted(df.year.unique()):
        gy = df[df.year == y]; g = gy[m.loc[gy.index]]
        if len(g) == 0:
            continue
        dy = (gy.exit_ts.max() - gy.ts_fill.min()).days or 1
        n, nt, ns, nm, wr, sr, av, per = row(g, dy)
        print(f"    {int(y)}: сделок {n:5d} ({per:.2f}/д) | TP {nt:5d} SL {ns:5d} TIME {nm:5d} | WR {wr:5.1f}% | ΣR {sr:+7.1f} avg {av:+.4f}")
print("\nDONE")
