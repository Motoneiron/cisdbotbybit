"""Портфель 2024-26: что если убрать tf7 (или только tf7-лонги). Капитал заново с $100."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
kd = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
mp = dict(zip(kd(t8), t8.vd_B))
df["v"] = np.where(df.prof == "tf8", [mp.get(x) for x in kd(df)], df.vd_conf)
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()


def portfolio(d, risk=0.01, start=100.0, max_pos=7):
    d = d.sort_values("t_in")
    items = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r_net.astype(float)))
    pe, heap, taken = {}, [], []
    for tin, tout, sym, r in items:
        while heap and heap[0] <= tin:
            heapq.heappop(heap)
        p = pe.get(sym)
        if p is not None and tin < p:
            continue
        if len(heap) >= max_pos:
            continue
        taken.append((tin, tout, r)); heapq.heappush(heap, tout); pe[sym] = tout
    ev = []
    for i, (tin, tout, r) in enumerate(taken):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = start; rm = {}; curve = [(ev[0][0] if ev else 0, bal)]
    for t, k, i in ev:
        tin, tout, r = taken[i]
        if k == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * risk * r
            else:
                rm[i] = bal * risk
        curve.append((t, bal))
    s = pd.Series([c[1] for c in curve])
    mdd = float(((s - s.cummax()) / s.cummax()).min() * 100)
    return bal, mdd, len(taken)


g = df[df.year >= 2024].copy()
S = g["dir"] == "SHORT"; L = g["dir"] == "LONG"; v = g.v
dep = (S & (v <= 0)) | (L & (v >= 0))
RULES = {
    "ДЕПЛОЙ (как в боте), весь поток": dep,
    "ДЕПЛОЙ, без tf7-лонгов": dep & ~((g.prof == "tf7") & (g["dir"] == "LONG")),
    "ДЕПЛОЙ, только tf8": dep & (g.prof == "tf8"),
    "ДЕПЛОЙ, только tf7": dep & (g.prof == "tf7"),
    "ДЕПЛОЙ, без tf7 целиком": dep & (g.prof != "tf7"),
}
print(f"OOS 2024-26, поток {len(g)} сд")
print(f"  {'правило':34} | {'взято':>6} | {'финал $':>11} | {'MaxDD':>7}")
for name, m in RULES.items():
    fin, mdd, n = portfolio(g[m.fillna(False)])
    print(f"  {name:34} | {n:>6} | {fin:>11,.0f} | {mdd:>6.1f}%")
print("\nDONE")
