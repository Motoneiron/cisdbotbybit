"""Портфели по годам: EMA3+min_stop vs vwap+min_stop vs min_stop — по профилям (исправлено)."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
tp = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
kk = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = kk(df); tp["k"] = kk(tp)
mp = dict(zip(tp.k, tp["r_1_0"]))
df["r"] = [mp.get(x) for x in df.k]
df = df[df.r.notna()].copy()
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1; V = df.vd_conf
E3 = ((L & (s > 0.0002)) | (S & (s < -0.0002))).fillna(False)
G = ((S & (V <= 0)) | (L & (V >= 0))).fillna(False)
MS = df.sp >= 0.005
VAR = {"EMA3+ms": E3 & MS, "vwap+ms": G & MS, "min_stop": MS, "EMA3+vwap+ms": E3 & G & MS}


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
    for t, kk_, i in ev:
        tin, tout, r = tk[i]
        if kk_ == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * risk * r
            else:
                rm[i] = bal * risk
        cur.append((t, bal))
    ss = pd.Series([c[1] for c in cur])
    return bal, float(((ss - ss.cummax()) / ss.cummax()).min() * 100), len(tk)


for scope, sub in (("tf8", df[df.prof == "tf8"]), ("tf7", df[df.prof == "tf7"]), ("tf7+tf8", df)):
    print(f"\n===== {scope} =====")
    for lab, m in VAR.items():
        g = sub[m.loc[sub.index]]
        out = []
        for y in sorted(df.year.unique()):
            f, _, k = pf(g[g.year >= y].copy())
            out.append(f"{int(y)}:${f:,.0f}")
        f, dd, k = pf(g.copy())
        g24 = g[g.year >= 2024]
        f24, dd24, k24 = pf(g24.copy())
        print(f"  {lab:14} | 2024-26: взято {k24:5d} ${f24:>10,.0f} ({dd24:>6.1f}%) | весь ${f:>12,.0f} ({dd:>6.1f}%)")
        print(f"  {'':14}   по годам (старт в году): " + " ".join(out))
print("\nDONE")
