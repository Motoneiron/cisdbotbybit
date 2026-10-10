"""Чистый портфель для C «минус тянем» (плюсовые закрываем на 6ч, минусовые тянем до 24ч).

Занятость: плюсовые → выход ≤6ч, минусовые → до касания/24ч.
Плюс вариант «тянем только глубокие минусы» и «тянем минусы + крупные плюсы».
"""
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
touch = np.minimum(d.t_tp_min.fillna(1e9), d.t_sl_min.fillna(1e9))

hold = {
    "C: тянем все минусы (g6<0)": op & (d.g6 < 0),
    "C: тянем минусы < -0.3R": op & (d.g6 < -0.3),
    "C2: тянем минусы + крупные плюсы(>0.3R)": op & ((d.g6 < 0) | (d.g6 > 0.3)),
    "B: тянем только плюсы(>0.3R)": op & (d.g6 > 0.3),
    "все до 24ч": op,
}
d["rC"] = np.where(hold["C: тянем все минусы (g6<0)"], d.r_24, d.r_6)
d["rC3"] = np.where(hold["C: тянем минусы < -0.3R"], d.r_24, d.r_6)
d["rC2"] = np.where(hold["C2: тянем минусы + крупные плюсы(>0.3R)"], d.r_24, d.r_6)
d["rB"] = np.where(hold["B: тянем только плюсы(>0.3R)"], d.r_24, d.r_6)
COL = {"C: тянем все минусы (g6<0)": "rC", "C: тянем минусы < -0.3R": "rC3",
       "C2: тянем минусы + крупные плюсы(>0.3R)": "rC2", "B: тянем только плюсы(>0.3R)": "rB",
       "все до 24ч": "r_24"}


def pf(g, rcol, held):
    x = g.copy()
    hor = np.where(held, 24 * 60, 6 * 60)
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
    return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(tk), int(held.sum()), x[rcol].sum()


print("tf8+min_stop 0.5%, $100, 7 слотов, риск 1% | честная занятость")
print(f"  {'вариант':42} | {'все годы: n / $ / MaxDD / ΣR':>44} | {'2024-26: n / $ / MaxDD':>30}")
rows = [("статика: крышка 6ч", "r_6", pd.Series(False, index=d.index))]
rows += [(lab, COL[lab], hold[lab]) for lab in hold]
for lab, col, hm in rows:
    f, md, n, nh, sr = pf(d, col, hm)
    g24 = d[d.year >= 2024]
    f2, m2, n2, nh2, sr2 = pf(g24, col, hm.loc[g24.index])
    print(f"  {lab:42} | {n:6d} ${f:>12,.0f} {md:>6.1f}% {sr:+8.1f} | {n2:5d} ${f2:>9,.0f} {m2:>6.1f}%")
print("\nDONE")
