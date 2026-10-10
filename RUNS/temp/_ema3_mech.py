"""Механизм EMA3-фильтра: «по направлению» или «отсев плоского |slope|»?

Сравниваю два правила на одном якоре:
 A) with-trend: (LONG & s>+thr) | (SHORT & s<-thr)
 B) magnitude: |s| > thr  (симметрично, отсекает плоское в обе стороны)
Портфель 2024-26, все годы, суммы/год, WR.
"""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3_r1.pkl")
tp = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
key = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = key(df); tp["k"] = key(tp)
mp = dict(zip(tp.k, tp["r_1_0"]))
df["r"] = [mp.get(x) for x in df.k]
df = df[df.r.notna()].copy()
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()


def wr(g):
    x = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (x.outcome == "tp").mean() if len(x) else float("nan")


def pf(d, risk=0.01, start=100.0, maxpos=7):
    d = d.sort_values("t_in")
    it = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r.astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, sym, r in it:
        while hp and hp[0] <= tin:
            heapq.heappop(hp)
        p = pe.get(sym)
        if p is not None and tin < p:
            continue
        if len(hp) >= maxpos:
            continue
        tk.append((tin, tout, r)); heapq.heappush(hp, tout); pe[sym] = tout
    ev = []
    for i, (tin, tout, r) in enumerate(tk):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = start; rm = {}; cur = [(ev[0][0] if ev else 0, bal)]
    for t, kk, i in ev:
        tin, tout, r = tk[i]
        if kk == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * risk * r
            else:
                rm[i] = bal * risk
        cur.append((t, bal))
    s = pd.Series([c[1] for c in cur])
    return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(tk)


L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1
print("== база: n=%d ΣR=%+.1f avg=%+.4f WR=%.1f%% ==" % (len(df), df.r.sum(), df.r.mean(), wr(df)))
A = lambda t: (L & (s > t)) | (S & (s < -t))
B = lambda t: s.abs() > t
print("\n=== портфель: A) по направлению  vs  B) |наклон|>thr ===")
print(f"  {'порог':>7} | {'A: n':>6} {'ΣR24':>7} {'$24-26':>9} {'DD':>6} {'$все':>10} | {'B: n':>6} {'ΣR24':>7} {'$24-26':>9} {'DD':>6} {'$все':>10}")
for thr in (0.0, 0.00005, 0.0001, 0.0002, 0.0004, 0.001, 0.002):
    ga = df[A(thr).fillna(False)]; gb = df[B(thr).fillna(False)]
    a4 = ga[ga.year >= 2024]; b4 = gb[gb.year >= 2024]
    fa, da, _ = pf(ga.copy()); fa4, da4, na = pf(a4.copy())
    fb, db, _ = pf(gb.copy()); fb4, db4, nb = pf(b4.copy())
    print(f"  {100*thr:6.3f}% | {na:6d} {a4.r.sum():+7.0f} ${fa4:>8,.0f} {da4:>5.1f}% ${fa:>9,.0f} | {nb:6d} {b4.r.sum():+7.0f} ${fb4:>8,.0f} {db4:>5.1f}% ${fb:>9,.0f}")

print("\n=== B) |наклон|>0.02%: ΣR и WR по годам ===")
gb = df[B(0.0002).fillna(False)]
for y, g in df.groupby("year"):
    gf = gb[gb.year == y]
    print(f"  {int(y)}: база ΣR={g.r.sum():+8.1f} WR={wr(g):.1f}% | B ΣR={gf.r.sum():+8.1f} WR={wr(gf):.1f}% взято {len(gf)}/{len(g)}")

print("\n=== B) |наклон|>0.02%: портфель по годам ===")
for lab, g in [("A 0.02% по направлению", df[A(0.0002).fillna(False)]), ("B 0.02% |наклон|", gb)]:
    out = []
    for y in sorted(df.year.unique()):
        f, _, _ = pf(g[g.year >= y].copy())
        out.append(f"{int(y)}:${f:,.0f}")
    f, d, n = pf(g.copy())
    print(f"  {lab:24} весь ${f:>10,.0f} ({d:>6.1f}%) | " + " ".join(out))

print("\n=== комбинация: B) |наклон|>0.02% AND min_stop 0.5% (2024-26 и все годы) ===")
g = df[B(0.0002).fillna(False) & (df.sp >= 0.005)]
f, d, n = pf(g.copy()); f4, d4, n4 = pf(g[g.year >= 2024].copy())
print(f"  n={n} весь ${f:,.0f} ({d:.1f}%) | 2024-26 n={n4} ${f4:,.0f} ({d4:.1f}%)")
print("\nDONE")
