"""WALK-FORWARD проверка «шортовый фильтр только на выбранных парах».

Выбор пар — ТОЛЬКО по 2020–2023 (avg S>0 < 0 в большинстве лет). Тест — 2024–2026,
капитал обнуляется на 2024-01-01. Сравниваем: без гейта | ДЕПЛОЙ | S-без-фильтра+L≥0 |
S≤0-только-выбранные+L≥0.
"""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
kd = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
mp = dict(zip(kd(t8), t8.vd_B))
df["vd_live"] = np.where(df.prof == "tf8", [mp.get(x) for x in kd(df)], df.vd_conf)
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()

S = df["dir"] == "SHORT"; L = df["dir"] == "LONG"; v = df.vd_live
ins = df[(df.year <= 2023) & S & (v > 0)]
print("ВЫБОР ПАР по 2020-23 (шорты с vd>0):")
sel = []
for sym, g in ins.groupby("sym"):
    yrs = [(int(y), x.r_net.mean(), len(x)) for y, x in g.groupby("year") if len(x) >= 50]
    neg = sum(1 for _, m, _ in yrs if m < 0)
    ok = neg >= max(2, len(yrs) - 1) and neg > len(yrs) / 2
    print(f"   {sym:5} лет={len(yrs)} минус={neg} avg={g.r_net.mean():+.3f} -> {'БЕРЁМ ФИЛЬТР' if ok else 'без фильтра'}")
    if ok:
        sel.append(sym)
print(f"   ОТОБРАНО (2020-23): {sel}")


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


oos = df[df.year >= 2024].copy()
So = oos["dir"] == "SHORT"; Lo = oos["dir"] == "LONG"; vo = oos.vd_live
long_ok = Lo & (vo >= 0)
RULES = {
    "raw (без гейта)": pd.Series(True, index=oos.index),
    "ДЕПЛОЙ (как в боте)": So & (vo <= 0) | long_ok,
    "S без фильтра + L>=0": So | long_ok,
    f"S<=0 только {sel} + L>=0": (So & oos.sym.isin(sel) & (vo <= 0)) | (So & ~oos.sym.isin(sel)) | long_ok,
}
print(f"\nOOS 2024-2026 (капитал стартует с $100 на 2024-01-01), сделок в потоке {len(oos)}:")
print(f"  {'правило':40} | {'взято':>6} | {'финал $':>12} | {'MaxDD':>7}")
for name, m in RULES.items():
    fin, mdd, n = portfolio(oos[m.fillna(False)])
    print(f"  {name:40} | {n:>6} | {fin:>12,.0f} | {mdd:>6.1f}%")
print("\nDONE")
