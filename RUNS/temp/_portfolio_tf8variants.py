"""Портфель под оба варианта tf8-якоря (A = закрытое 30m-ведро, B = частичное на конфирме)."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
k = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
mp = dict(zip(k(t8), t8.vd_B))
df["vd_B"] = [mp.get(x) for x in k(df)]
# композит: tf7 → vd_conf (боевой якорь совпадает), tf8 → вариант B
df["vd_live"] = np.where(df.prof == "tf8", df.vd_B, df.vd_conf)
print(f"NaN: vd_B {int(df.vd_B.isna().sum())} | vd_live {int(df.vd_live.isna().sum())}")


def to_min(c):
    return ((pd.to_datetime(c) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")


df["t_in"] = to_min(df.ts_fill); df["t_out"] = to_min(df.exit_ts)
df = df[df.t_out > df.t_in].copy()


def portfolio(d, risk=0.01, start=100.0, max_pos=7):
    d = d.sort_values("t_in")
    items = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r_net.astype(float)))
    pair_end, heap, taken = {}, [], []
    for tin, tout, sym, r in items:
        while heap and heap[0] <= tin:
            heapq.heappop(heap)
        pe = pair_end.get(sym)
        if pe is not None and tin < pe:
            continue
        if len(heap) >= max_pos:
            continue
        taken.append((tin, tout, r)); heapq.heappush(heap, tout); pair_end[sym] = tout
    ev = []
    for i, (tin, tout, r) in enumerate(taken):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = start; risk_map = {}; curve = [(ev[0][0] if ev else 0, bal)]
    for t, kind, i in ev:
        tin, tout, r = taken[i]
        if kind == 0:
            if i in risk_map:
                bal += risk_map.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * risk * r
            else:
                risk_map[i] = bal * risk
        curve.append((t, bal))
    s = pd.Series([c[1] for c in curve])
    mdd = float(((s - s.cummax()) / s.cummax()).min() * 100)
    cur = pd.DataFrame(curve, columns=["t", "bal"]); cur["year"] = pd.to_datetime(cur.t, unit="m").dt.year
    return bal, mdd, len(taken), cur.groupby("year")["bal"].last()


print(f"база {len(df)}")
for tag, col in (("A: tf8 = закрытое 30m-ведро", "vd_conf"), ("B: tf8 = частичное ведро (боевой)", "vd_live")):
    S = df["dir"] == "SHORT"; L = df["dir"] == "LONG"; vc = df[col]
    rules = {
        "raw": pd.Series(True, index=df.index),
        "DEP (S<=0/L>=0)": (S & (vc <= 0)) | (L & (vc >= 0)),
        "shorts БЕЗ фильтра / L>=0": S | (L & (vc >= 0)),
        "S<=1 / L>=0": (S & (vc <= 1)) | (L & (vc >= 0)),
    }
    print(f"\n=== tf8-якорь {tag} ===")
    print(f"  {'правило':28} | {'взято':>6} | {'финал $':>13} | {'MaxDD':>7}")
    for name, m in rules.items():
        fin, mdd, n, _ = portfolio(df[m.fillna(False)])
        print(f"  {name:28} | {n:>6} | {fin:>13,.0f} | {mdd:>6.1f}%")
print("\nDONE")
