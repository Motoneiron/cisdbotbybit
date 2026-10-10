"""Трендовый гейт по дневной EMA50: лонги только выше, шорты только ниже.

Проверка по годам + OOS 2024-26 + портфельный сим (7 слотов) + комбинация с деплойным vwap-гейтом.
"""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_regime_live.pkl")
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
kd = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
mp = dict(zip(kd(t8), t8.vd_B))
df["v"] = np.where(df.prof == "tf8", [mp.get(x) for x in kd(df)], df.vd_conf)
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
S = df["dir"] == "SHORT"; L = df["dir"] == "LONG"; v = df.v; tr = df.trend


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


print("=== ПО ГОДАМ: ΣR лонгов и шортов по знаку trend (EMA50 дн.) ===")
for y, g in df.groupby("year"):
    l = g[g["dir"] == "LONG"]; s = g[g["dir"] == "SHORT"]
    print(f"  {int(y)}: LONG выше {l[l.trend > 0].r_net.sum():+7.1f} (n={len(l[l.trend>0])}) | "
          f"LONG ниже {l[l.trend <= 0].r_net.sum():+7.1f} (n={len(l[l.trend<=0])}) || "
          f"SHORT ниже {s[s.trend < 0].r_net.sum():+7.1f} | SHORT выше {s[s.trend >= 0].r_net.sum():+7.1f}")

RULES = {
    "raw (без гейта)": pd.Series(True, index=df.index),
    "ДЕПЛОЙ vwap (S<=0/L>=0)": (S & (v <= 0)) | (L & (v >= 0)),
    "ТРЕНД (L>EMA50 / S<EMA50)": (L & (tr > 0)) | (S & (tr < 0)),
    "ТРЕНД L>EMA50, шорты все": (L & (tr > 0)) | S,
    "ДЕПЛОЙ + ТРЕНД по лонгам": (L & (v >= 0) & (tr > 0)) | (S & (v <= 0)),
    "L>EMA50 & vd>=0 / S все": (L & (v >= 0) & (tr > 0)) | S,
}
print("\n=== СУММЫ: вся история / 2024-26 ===")
for n, m in RULES.items():
    g = df[m.fillna(False)]; g4 = g[g.year >= 2024]
    print(f"  {n:28} | весь: n={len(g):6d} WR={wr(g):5.1f}% ΣR={g.r_net.sum():+8.1f} | "
          f"2024-26: n={len(g4):5d} WR={wr(g4):5.1f}% ΣR={g4.r_net.sum():+8.1f}")


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


print("\n=== ПОРТФЕЛЬ 2024-26 (капитал заново с $100, 7 слотов, 1%) ===")
g = df[df.year >= 2024].copy()
S2 = g["dir"] == "SHORT"; L2 = g["dir"] == "LONG"; v2 = g.v; tr2 = g.trend
R2 = {
    "raw": pd.Series(True, index=g.index),
    "ДЕПЛОЙ vwap": (S2 & (v2 <= 0)) | (L2 & (v2 >= 0)),
    "ТРЕНД (L>EMA50/S<EMA50)": (L2 & (tr2 > 0)) | (S2 & (tr2 < 0)),
    "ТРЕНД L>EMA50, шорты все": (L2 & (tr2 > 0)) | S2,
    "L>EMA50 & vd>=0 / S все": (L2 & (v2 >= 0) & (tr2 > 0)) | S2,
    "L>EMA50 & vd>=0 / S vd<=0": (L2 & (v2 >= 0) & (tr2 > 0)) | (S2 & (v2 <= 0)),
}
for n, m in R2.items():
    fin, mdd, nn = portfolio(g[m.fillna(False)])
    print(f"  {n:28} | взято {nn:5d} | финал ${fin:>10,.0f} | MaxDD {mdd:>6.1f}%")
print("\nDONE")
