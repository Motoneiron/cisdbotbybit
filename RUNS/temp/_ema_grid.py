"""Сетка EMA для дневного тренд-гейта: EMA20/50/100/200 (+ наклоны) по дневным свечам.

Правило: лонги только выше своей дневной EMAk, шорты только ниже. Плюс варианты с наклоном.
"""
import heapq
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
KS = (20, 50, 100, 200)


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


df = pd.read_pickle(f"{BASE}/stream_regime_live.pkl").copy()
df["from_ts"] = pd.to_datetime(df["from_ts"])
for k in KS:
    df[f"e{k}"] = np.nan
    df[f"s{k}"] = np.nan
for sym in sorted(df.sym.unique()):
    d30, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
    d30.index = pd.DatetimeIndex(d30.index)
    dd = pd.DataFrame({"close": d30["close"].resample("1D").last()}).dropna()
    idx = df.index[df.sym == sym]
    fts = df.loc[idx, "from_ts"].to_numpy()
    i = np.searchsorted(dd.index.to_numpy() + np.timedelta64(1, "D"), fts, "right") - 1
    good = (i >= 200) & (i < len(dd))
    pos = np.clip(np.where(good, i, 0), 0, len(dd) - 1)
    cl = dd["close"].to_numpy(float)
    for k in KS:
        e = dd["close"].ewm(span=k, adjust=False, min_periods=k).mean()
        ea = e.to_numpy(float)
        df.loc[idx, f"e{k}"] = np.where(good, cl[pos] / ea[pos] - 1.0, np.nan)
        s = (e / e.shift(10) - 1.0).to_numpy(float)
        df.loc[idx, f"s{k}"] = np.where(good, s[pos], np.nan)
    print(f"  [{sym}] ok", flush=True)
df.to_pickle(f"{BASE}/stream_ema_grid.pkl")

L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"


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
    return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(taken)


df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"

RULES = {"raw": pd.Series(True, index=df.index)}
for k in KS:
    RULES[f"L>E{k}д / S<E{k}д"] = (L & (df[f"e{k}"] > 0)) | (S & (df[f"e{k}"] < 0))
    RULES[f"L>E{k}д / шорты все"] = (L & (df[f"e{k}"] > 0)) | S
RULES["L>E50д & s50>0 / S все"] = (L & (df.e50 > 0) & (df.s50 > 0)) | S
RULES["L>E100д & s100>0 / S все"] = (L & (df.e100 > 0) & (df.s100 > 0)) | S
RULES["L>E20д & L>E50д / S<E20д&S<E50д"] = (L & (df.e20 > 0) & (df.e50 > 0)) | (S & (df.e20 < 0) & (df.e50 < 0))

print("\n=== СУММЫ (весь период / 2024-26) ===", flush=True)
for n, m in RULES.items():
    g = df[m.fillna(False)]; g4 = g[g.year >= 2024]
    print(f"  {n:34} | весь n={len(g):6d} WR={wr(g):5.1f}% ΣR={g.r_net.sum():+8.1f} | "
          f"2024-26 n={len(g4):5d} WR={wr(g4):5.1f}% ΣR={g4.r_net.sum():+8.1f}", flush=True)

g = df[df.year >= 2024].copy()
Lg = g["dir"] == "LONG"; Sg = g["dir"] == "SHORT"
print("\n=== ПОРТФЕЛЬ 2024-26 ($100, 7 слотов, 1%) ===", flush=True)
best = []
for n, m in {"raw": pd.Series(True, index=g.index),
             "L>E20д/S<E20д": (Lg & (g.e20 > 0)) | (Sg & (g.e20 < 0)),
             "L>E50д/S<E50д": (Lg & (g.e50 > 0)) | (Sg & (g.e50 < 0)),
             "L>E100д/S<E100д": (Lg & (g.e100 > 0)) | (Sg & (g.e100 < 0)),
             "L>E200д/S<E200д": (Lg & (g.e200 > 0)) | (Sg & (g.e200 < 0)),
             "L>E20&50д / S<E20&50д": (Lg & (g.e20 > 0) & (g.e50 > 0)) | (Sg & (g.e20 < 0) & (g.e50 < 0)),
             "L>E50&100д / S<E50&100д": (Lg & (g.e50 > 0) & (g.e100 > 0)) | (Sg & (g.e50 < 0) & (g.e100 < 0)),
             }.items():
    fin, mdd, nn = portfolio(g[m.fillna(False)])
    print(f"  {n:26} | взято {nn:5d} | ${fin:>10,.0f} | MaxDD {mdd:>6.1f}%", flush=True)
print("\n=== по годам: ЛОНГИ выше/ниже каждой EMA (ΣR) ===", flush=True)
for k in KS:
    row = []
    for y, gg in df.groupby("year"):
        l = gg[gg["dir"] == "LONG"]
        row.append(f"{int(y)}: {l[l[f'e{k}']>0].r_net.sum():+6.0f}/{l[l[f'e{k}']<=0].r_net.sum():+6.0f}")
    print(f"  E{k}: " + " | ".join(row), flush=True)
print("\nDONE", flush=True)
