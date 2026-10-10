"""EMA3 по профилям — полная картина: сигналы (ΣR/avg/WR) И портфель (7 слотов, $100).

Сигнальные суммы — по ВСЕМ сигналам профиля; портфельные — по взятым (после 1 поз/пара и лимита 7).
"""
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
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1
E3 = (L & (s > 0.0002)) | (S & (s < -0.0002))
MS = df.sp >= 0.005
V = df.vd_conf
G = (S & (V <= 0)) | (L & (V >= 0))
M = {"база (всё)": pd.Series(True, index=df.index), "EMA3 1H 0.02%": E3, "EMA3 + min_stop 0.5%": E3 & MS,
     "min_stop 0.5%": MS, "vwap-гейт": G, "vwap + min_stop 0.5%": G & MS}
M = {k: v.fillna(False) for k, v in M.items()}


def w(g):
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


print("=== 2024-26: СИГНАЛЫ (ΣR/avg/WR по всем сигналам) + ПОРТФЕЛЬ по профилям ===")
for scope, sub in (("tf7", df[df.prof == "tf7"]), ("tf8", df[df.prof == "tf8"]), ("tf7+tf8", df)):
    print(f"\n--- {scope} ---")
    print(f"  {'вариант':22} | {'сигн. n':>7} {'WR':>6} {'avg':>8} {'ΣR сигн.':>10} | {'взято':>6} {'$ (2024)':>10} {'MaxDD':>7}")
    for lab, m in M.items():
        g = sub[m.loc[sub.index]]
        g24 = g[g.year >= 2024]
        b24 = sub[sub.year >= 2024]
        f, dd, n = pf(b24.copy())
        print(f"  {lab:22} | {len(g24):7d} {w(g24):5.1f}% {g24.r.mean():+8.4f} {g24.r.sum():+10.1f} | {n:6d} ${f:>9,.0f} {dd:>6.1f}%")
print("\n=== то же, ВСЕ ГОДЫ ===")
for scope, sub in (("tf7", df[df.prof == "tf7"]), ("tf8", df[df.prof == "tf8"]), ("tf7+tf8", df)):
    print(f"\n--- {scope} ---")
    for lab, m in M.items():
        g = sub[m.loc[sub.index]]
        f, dd, n = pf(g.copy())
        print(f"  {lab:22} | сигн. n={len(g):6d} WR={w(g):5.1f}% avg={g.r.mean():+.4f} ΣR={g.r.sum():+9.1f} | взято {n:6d} ${f:>11,.0f} MaxDD {dd:>6.1f}%")
print("\nDONE")
