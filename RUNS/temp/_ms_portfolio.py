import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
df = df[df["r_1_0"].notna()].copy()
df["r"] = df["r_1_0"]
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
k = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
mp = dict(zip(k(t8), t8.vd_B))
df["v"] = np.where(df.prof == "tf8", [mp.get(x) for x in k(df)], df.vd_conf)
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")


def pf(d, risk=0.01, start=100.0, maxpos=7):
    d = d.sort_values("t_in")
    it = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r.astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, s, r in it:
        while hp and hp[0] <= tin:
            heapq.heappop(hp)
        p = pe.get(s)
        if p is not None and tin < p:
            continue
        if len(hp) >= maxpos:
            continue
        tk.append((tin, tout, r)); heapq.heappush(hp, tout); pe[s] = tout
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


D = ((df["dir"] == "SHORT") & (df.v <= 0)) | ((df["dir"] == "LONG") & (df.v >= 0))
rows = [
    ("весь поток", pd.Series(True, index=df.index)),
    ("ДЕПЛОЙ vwap", D),
    ("ДЕПЛОЙ + min_stop 0.5%", D & (df.sp >= 0.005)),
    ("только min_stop 0.4%", df.sp >= 0.004),
    ("только min_stop 0.5%", df.sp >= 0.005),
    ("только min_stop 0.6%", df.sp >= 0.006),
    ("ДЕПЛОЙ + ms0.5% + L>EMA50(кауз)", D & (df.sp >= 0.005)),
]
print("портфель (1 поз/пара, 7 слотов, риск 1%):")
print(f"  {'правило':30} | {'все годы: n / $ / MaxDD':>34} | {'2024-26: n / $ / MaxDD':>32}")
for lab, m in rows:
    a = df[m.fillna(False)]
    f1, d1, n1 = pf(a.copy())
    b = a[a.year >= 2024]
    f2, d2, n2 = pf(b.copy())
    print(f"  {lab:30} | {n1:5d}  ${f1:>11,.0f}  {d1:>6.1f}% | {n2:5d}  ${f2:>11,.0f}  {d2:>6.1f}%")
print("\nDONE")
