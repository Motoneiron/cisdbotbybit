"""Портфель для правил B/C с ЧЕСТНОЙ занятостью: неудержанные закрываются на 6ч."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
MAKER, TAKER = 0.00036, 0.0010
d = pd.read_pickle(f"{BASE}/stream_tf8_timeout.pkl")
d = d[d["r_6"].notna() & (d.sp >= 0.005)].copy()
d["ts_fill"] = pd.to_datetime(d.ts_fill)
d["t_in"] = ((d.ts_fill - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
d["fee"] = (MAKER + TAKER) / d.sp
d["g6"] = d["r_6"] + d["fee"]
op = d["res_6"] == "time"
d["rB"] = np.where(op & (d.g6 > 0.3), d.r_24, d.r_6)
d["rC"] = np.where(op & (d.g6 < -0.3), d.r_24, d.r_6)
touch = np.minimum(d.t_tp_min.fillna(1e9), d.t_sl_min.fillna(1e9))


def pf(g, rcol, held_mask):
    x = g.copy()
    hor = np.where(held_mask, 24 * 60, 6 * 60)
    x["t_out"] = x.t_in + np.minimum(touch.loc[x.index].fillna(1e9), hor).astype("int64")
    it = list(zip(x.t_in, x.t_out, x.sym, x[rcol].astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, sym, r in it:
        while hp and hp[0] <= tin:
            heapq.heappop(hp)
        p = pe.get(sym)
        if p is not None and tin < p:
            continue
        if len(hp) >= 7:
            continue
        tk.append((tin, tout, r)); heapq.heappush(hp, tout); pe[sym] = tout
    ev = []
    for i, (tin, tout, r) in enumerate(tk):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = 100.0; rm = {}; cur = [(ev[0][0] if ev else 0, bal)]
    for t, k, i in ev:
        tin, tout, r = tk[i]
        if k == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * 0.01 * r
            else:
                rm[i] = bal * 0.01
        cur.append((t, bal))
    s = pd.Series([c[1] for c in cur])
    return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(tk), int(held_mask.sum())


print("tf8+ms0.5%, PORTFOLIO $100, 7 слотов, честная занятость")
cases = [("статика 6ч", "r_6", pd.Series(False, index=d.index)),
         ("все до 24ч", "r_24", pd.Series(True, index=d.index)),
         ("B «плюс тянем» 0.3R", "rB", op & (d.g6 > 0.3)),
         ("B «плюс тянем» 0 (любой плюс)", "r_6", op & (d.g6 > 0))]
d["rB0"] = np.where(op & (d.g6 > 0), d.r_24, d.r_6)
cases[3] = ("B «плюс тянем» >0", "rB0", op & (d.g6 > 0))
for lab, col, hm in cases:
    f, md, n, nh = pf(d, col, hm)
    g24 = d[d.year >= 2024]; hm24 = hm.loc[g24.index]
    f2, m2, n2, nh2 = pf(g24, col, hm24)
    print(f"  {lab:30} | все: n={n:6d} (тянем {nh:5d}) ${f:>12,.0f} ({md:>6.1f}%) | 2024-26: n={n2:5d} (тянем {nh2:4d}) ${f2:>9,.0f} ({m2:>6.1f}%)")
print("\nDONE")
