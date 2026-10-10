"""КАУЗАЛЬНЫЙ тренд-гейт: только ПОЛНОСТЬЮ закрытые дневные свечи (без look-ahead).

Ошибка предыдущего _regime_longs.py: индекс `searchsorted(dd.index, fts) - 1` брал ТЕКУЩИЙ
(незакрытый) день → в тренд попадал будущий close дня. Здесь: последний день, у которого
close наступил ДО from_ts: i = searchsorted(labels + 1d, fts, 'right') - 1.
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


df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl").copy()
df["from_ts"] = pd.to_datetime(df["from_ts"])
for k in KS:
    df[f"e{k}"] = np.nan
for sym in sorted(df.sym.unique()):
    d30, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
    d30.index = pd.DatetimeIndex(d30.index)
    dd = pd.DataFrame({"close": d30["close"].resample("1D", label="left", closed="left").last()}).dropna()
    labels_end = (dd.index + pd.Timedelta(days=1)).to_numpy()
    idx = df.index[df.sym == sym]
    fts = df.loc[idx, "from_ts"].to_numpy()
    i = np.searchsorted(labels_end, fts, "right") - 1
    good = (i >= 200) & (i < len(dd))
    pos = np.clip(np.where(good, i, 0), 0, len(dd) - 1)
    cl = dd["close"].to_numpy(float)
    for k in KS:
        e = dd["close"].ewm(span=k, adjust=False, min_periods=k).mean().to_numpy(float)
        df.loc[idx, f"e{k}"] = np.where(good, cl[pos] / e[pos] - 1.0, np.nan)
    print(f"  [{sym}] ok", flush=True)
df.to_pickle(f"{BASE}/stream_ema_causal.pkl")

L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"
LO = df.outcome == "tp"
print("\n=== КАУЗАЛЬНЫЙ тренд: ЛОНГИ по зонам (EMA50, только закрытые дни) ===", flush=True)
bins = [-1, -0.10, -0.03, 0.0, 0.03, 0.10, 10]
lbl = ["<-10%", "-10..-3%", "-3..0%", "0..+3%", "3..10%", ">10%"]
l = df[L].copy(); l["z"] = pd.cut(l.e50, bins=bins, labels=lbl)
print(l.groupby("z", observed=True).apply(lambda g: pd.Series({"n": len(g), "WR": round(wr(g), 1), "ΣR": round(g.r_net.sum(), 1), "avg": round(g.r_net.mean(), 3)}), include_groups=False).to_string(), flush=True)
s = df[S].copy(); s["z"] = pd.cut(s.e50, bins=bins, labels=lbl)
print("\n=== ШОРТЫ по зонам ===", flush=True)
print(s.groupby("z", observed=True).apply(lambda g: pd.Series({"n": len(g), "WR": round(wr(g), 1), "ΣR": round(g.r_net.sum(), 1), "avg": round(g.r_net.mean(), 3)}), include_groups=False).to_string(), flush=True)

print("\n=== ЛОНГИ по годам: выше/ниже закрытой EMA50 ===", flush=True)
for y, g in df.groupby("year"):
    ll = g[g["dir"] == "LONG"]
    a = ll[ll.e50 > 0]; b = ll[ll.e50 <= 0]
    print(f"  {int(y)}: выше {a.r_net.sum():+7.1f} (n={len(a):5d}) WR={wr(a):5.1f}% | ниже {b.r_net.sum():+7.1f} (n={len(b):5d}) WR={wr(b):5.1f}%", flush=True)
print("\n=== ШОРТЫ по годам: ниже/выше закрытой EMA50 ===", flush=True)
for y, g in df.groupby("year"):
    ss = g[g["dir"] == "SHORT"]
    a = ss[ss.e50 < 0]; b = ss[ss.e50 >= 0]
    print(f"  {int(y)}: ниже {a.r_net.sum():+7.1f} | выше {b.r_net.sum():+7.1f}", flush=True)

df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"
V = df.vd_conf


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
    sv = pd.Series([c[1] for c in curve])
    return bal, float(((sv - sv.cummax()) / sv.cummax()).min() * 100), len(taken)


RULES = {
    "raw": pd.Series(True, index=df.index),
    "ДЕПЛОЙ vwap (S vd<=0/L vd>=0)": (S & (V <= 0)) | (L & (V >= 0)),
}
for k in KS:
    RULES[f"ТРЕНД L>E{k}/S<E{k}"] = (L & (df[f"e{k}"] > 0)) | (S & (df[f"e{k}"] < 0))
    RULES[f"L>E{k}, шорты все"] = (L & (df[f"e{k}"] > 0)) | S
RULES["L>E50 & vd>=0 / S все"] = (L & (df.e50 > 0) & (V >= 0)) | S
print("\n=== СУММЫ + ПОРТФЕЛЬ 2024-26 ===", flush=True)
print(f"  {'правило':30} | {'весь: n/WR/ΣR':>28} | {'2024-26: n/WR/ΣR':>26} | портфель2024-26 | MaxDD", flush=True)
g4 = df[df.year >= 2024]
for n, m in RULES.items():
    g = df[m.fillna(False)]
    gg = g4[m.fillna(False).reindex(g4.index).fillna(False)]
    fin, mdd, nn = portfolio(gg)
    print(f"  {n:30} | {len(g):6d} {wr(g):5.1f}% {g.r_net.sum():+8.1f} | {len(gg):6d} {wr(gg):5.1f}% {gg.r_net.sum():+8.1f} | ${fin:>9,.0f} | {mdd:>6.1f}%", flush=True)
print("\nDONE", flush=True)
