"""Грид vwap-правил на ЧИСТОМ контуре — полные годы + OOS-разбиение.

Продолжение _gate_grid_portfolio.py (оборванная сессия 14.09): вывод ВСЕХ годов
для walk-forward-проверки (in-sample 2020-24, OOS 2025-26). Боевой портфель:
7 слотов, 1 поз/пара, риск 1%, реинвест. Якорь: vd_conf (лайв).
"""
import heapq

import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_ungated_v2.pkl")


def to_min(col):
    return ((pd.to_datetime(col) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")


df["t_in"] = to_min(df.ts_fill)
df["t_out"] = to_min(df.exit_ts)
df = df[df.t_out > df.t_in].copy()
S = df["dir"] == "SHORT"
L = df["dir"] == "LONG"
vc = df.vd_conf


def portfolio(d, risk_pct=0.01, start=100.0, max_pos=7):
    d = d.sort_values("t_in")
    d = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r_net.astype(float)))
    pair_end = {}
    open_heap = []
    taken = []
    skip_pair = skip_lim = 0
    max_conc = 0
    for tin, tout, sym, r in d:
        while open_heap and open_heap[0] <= tin:
            heapq.heappop(open_heap)
        pe = pair_end.get(sym)
        if pe is not None and tin < pe:
            skip_pair += 1
            continue
        if len(open_heap) >= max_pos:
            skip_lim += 1
            continue
        taken.append((tin, tout, r))
        heapq.heappush(open_heap, tout)
        pair_end[sym] = tout
        if len(open_heap) > max_conc:
            max_conc = len(open_heap)
    ev = []
    for idx, (tin, tout, r) in enumerate(taken):
        ev.append((tin, 1, idx))
        ev.append((tout, 0, idx))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = start
    risks = {}
    curve = [(ev[0][0] if ev else 0, balance)]
    for t, kind, idx in ev:
        tin, tout, r = taken[idx]
        if kind == 0:
            if idx in risks:
                balance += risks.pop(idx) * r
        else:
            if tout <= tin:
                balance += balance * risk_pct * r
            else:
                risks[idx] = balance * risk_pct
        curve.append((t, balance))
    s = pd.Series([c[1] for c in curve])
    mdd = float(((s - s.cummax()) / s.cummax()).min() * 100)
    cur = pd.DataFrame(curve, columns=["t", "bal"])
    cur["year"] = pd.to_datetime(cur.t, unit="m").dt.year
    yearly = cur.groupby("year")["bal"].last()
    return balance, mdd, {"n": len(taken), "sp": skip_pair, "sl": skip_lim, "mc": max_conc}, yearly


RULES = {
    "raw (без гейта)": pd.Series(True, index=df.index),
    "DEP: S<=0 / L>=0": (S & (vc <= 0)) | (L & (vc >= 0)),
    "S<=0, L все": (S & (vc <= 0)) | L,
    "S все, L>=0": S | (L & (vc >= 0)),
    "S<=0.5 / L>=0": (S & (vc <= 0.5)) | (L & (vc >= 0)),
    "S<=1 / L>=0": (S & (vc <= 1)) | (L & (vc >= 0)),
    "S<=0 / L>=-1": (S & (vc <= 0)) | (L & (vc >= -1)),
    "S<=0 / L>=0.5": (S & (vc <= 0)) | (L & (vc >= 0.5)),
    "S<=0 / L>=1": (S & (vc <= 0)) | (L & (vc >= 1)),
}

years = list(range(2020, 2027))
print(f"=== база {len(df)} | {pd.to_datetime(df.t_in.min(), unit='m')} .. {pd.to_datetime(df.t_out.max(), unit='m')} ===")
print(f"{'правило':20} | {'взято':>6} | {'финал$':>12} | {'MaxDD':>6} | " +
      " | ".join(f"{y}" for y in years) + " | OOS25-26")
for name, mask in RULES.items():
    fin, mdd, st, yearly = portfolio(df[mask])
    ycol = " | ".join(f"{int(yearly.get(y, float('nan'))):,}" for y in years)
    oos = yearly.get(2026, float("nan")) / max(yearly.get(2024, 1.0), 1e-9)
    print(f"{name:20} | {st['n']:>6} | {fin:>12,.0f} | {mdd:>6.1f}% | {ycol} | x{oos:,.0f}", flush=True)
