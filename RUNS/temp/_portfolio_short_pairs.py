"""Портфель: шортовый фильтр только там, где он реально работает (BTC/BNB/ETH)."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
kd = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["vd_live"] = np.where(df.prof == "tf8", [dict(zip(kd(t8), t8.vd_B)).get(x) for x in kd(df)], df.vd_conf)
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
S = df["dir"] == "SHORT"; L = df["dir"] == "LONG"; v = df.vd_live


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
    cur = pd.DataFrame(curve, columns=["t", "bal"]); cur["year"] = pd.to_datetime(cur.t, unit="m").dt.year
    return bal, mdd, len(taken), cur.groupby("year")["bal"].last()


MAJORS = ["BTC", "BNB", "ETH"]
short_ok_majors = S & df.sym.isin(MAJORS) & (v <= 0)      # фильтруем шорты только по майорам
short_all = S
long_ok = L & (v >= 0)

RULES = {
    "raw (без гейта)": pd.Series(True, index=df.index),
    "ДЕПЛОЙ: S<=0/L>=0 (как в боте)": short_all & (v <= 0) | long_ok,
    "S без фильтра + L>=0": short_all | long_ok,
    "S<=0 только BTC/BNB/ETH + L>=0": short_ok_majors | short_all & ~df.sym.isin(MAJORS) | long_ok,
    "S<=0 только майоры, шорты прочих БЕЗ + L>=0": short_ok_majors | (short_all & ~df.sym.isin(MAJORS)) | long_ok,
}
print(f"база {len(df)}")
print(f"  {'правило':46} | {'взято':>6} | {'финал $':>13} | {'MaxDD':>7}")
for name, m in RULES.items():
    fin, mdd, n, _ = portfolio(df[m.fillna(False)])
    print(f"  {name:46} | {n:>6} | {fin:>13,.0f} | {mdd:>6.1f}%")
print("\nDONE")
