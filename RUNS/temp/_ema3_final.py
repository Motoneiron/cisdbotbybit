"""EMA3 на ИСПРАВЛЕННОМ потоке (r_1_0, TP=1R, ветка TIME починена).

base = stream_tp_grid.pkl (r_1_0, sp, corrected TIME) + slope_* из stream_ema3.pkl (по hash|prof).
"""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl").copy()
df["r"] = df["r_1_0"]
e3 = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
key = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = key(df); e3["k"] = key(e3)
sl = e3.set_index("k")[["slope_tf7", "slope_tf8", "slope_h1"]].rename(
    columns={"slope_tf7": "s4h", "slope_tf8": "s8h", "slope_h1": "s1h"})
df = df.join(sl, on="k")
t8 = pd.read_pickle(f"{BASE}/tf8_vd_variants.pkl")[["hash", "prof", "vd_B"]]
t8["k"] = key(t8)
mp = dict(zip(t8.k, t8.vd_B))
df["v"] = np.where(df.prof == "tf8", [mp.get(x) for x in df.k], df.vd_conf)
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def pf(d, risk=0.01, start=100.0, maxpos=7):
    d = d.sort_values("t_in")
    it = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r.astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, sym, r in it:
        while hp and hp[0] <= tin:
            heapq.heappop(hp)
        p = pe.get(sym)
        if p is not None and tin < p:
            continue
        if len(hp) >= maxpos:
            continue
        tk.append((tin, tout, r)); heapq.heappush(hp, tout); pe[sym] = tout
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


L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"
D = (S & (df.v <= 0)) | (L & (df.v >= 0))
MS = df.sp >= 0.005
print("== база (исправленный поток): n=%d ΣR=%+.1f avg=%+.4f WR=%.1f%% ==" % (len(df), df.r.sum(), df.r.mean(), wr(df)))

print("\n=== портфель ВЕСЬ ПЕРИОД / 2024-26 ===")
rows = [("raw", pd.Series(True, index=df.index)), ("ДЕПЛОЙ vwap", D), ("ДЕПЛОЙ+min_stop0.5%", D & MS)]
for nm, c in [("1h", "s1h"), ("4h", "s4h"), ("8h", "s8h")]:
    s = df[c]
    for thr in (0.0, 0.0001, 0.0002, 0.0004):
        rows.append((f"EMA3 {nm} {100*thr:.2f}%", (L & (s > thr)) | (S & (s < -thr))))
    s = df[c]
    rows.append((f"EMA3 {nm} 0.02%+ms0.5%", ((L & (s > 0.0002)) | (S & (s < -0.0002))) & MS))
print(f"  {'правило':26} | {'все годы':>28} | {'2024-26':>28}")
for lab, m in rows:
    a = df[m.fillna(False)]
    f1, d1, n1 = pf(a.copy())
    b = a[a.year >= 2024]
    f2, d2, n2 = pf(b.copy())
    print(f"  {lab:26} | {n1:5d} ΣR={a.r.sum():+8.0f} ${f1:>10,.0f} {d1:>6.1f}% | {n2:5d} ΣR={b.r.sum():+8.0f} ${f2:>10,.0f} {d2:>6.1f}%")

print("\n=== EMA3 1h 0.02%: ΣR и WR по годам (база vs фильтр) ===")
s = df.s1h
m = ((L & (s > 0.0002)) | (S & (s < -0.0002)))
print(f"  {'год':6}{'база ΣR':>10}{'фильтр ΣR':>11}{'база WR':>9}{'фильтр WR':>10}{'взято':>8}{'из':>8}")
fl = df[m.fillna(False)]
for y, g in df.groupby("year"):
    gf = fl[fl.year == y]
    print(f"  {int(y):<6}{g.r.sum():>+10.1f}{gf.r.sum():>+11.1f}{wr(g):>8.1f}%{wr(gf):>9.1f}%{len(gf):>8d}{len(g):>8d}")

print("\n=== EMA3 1h 0.02%: портфель по годам (капитал непрерывный, старт $100) ===")
for lab, mm in [("raw", pd.Series(True, index=df.index)), ("ДЕПЛОЙ vwap", D), ("EMA3 1h 0.02%", m), ("ДЕПЛОЙ+EMA3 1h 0.02%", D & ((df["dir"] != "LONG") | (df.s1h > 0.0002)))]:
    a = df[mm.fillna(False)]
    out = []
    for y in sorted(df.year.unique()):
        f, _, _ = pf(a[a.year >= y].copy())
        out.append(f"{int(y)}:${f:,.0f}")
    f, d, n = pf(a.copy())
    print(f"  {lab:24} весь ${f:>10,.0f} ({d:>6.1f}%) | " + " ".join(out))
print("\nDONE")
