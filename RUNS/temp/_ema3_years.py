"""EMA3 1H slope: устойчивость по годам (суммы, WR) + портфель по годам + комбинации с vwap."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def pf(d, risk=0.01, start=100.0, maxpos=7):
    d = d.sort_values("t_in")
    it = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r_net.astype(float)))
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


df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; V = df.vd_conf
D = (S & (V <= 0)) | (L & (V >= 0))
s = df["slope_1h"]

print("=== EMA3 1H slope: ΣR и WR по годам (весь поток = база) ===")
print(f"  {'год':6}{'база':>16}{'thr0':>16}{'thr0.01%':>16}{'thr0.02%':>16}{'thr0.04%':>16}")
for y, g in df.groupby("year"):
    l = g[g["dir"] == "LONG"]; sh = g[g["dir"] == "SHORT"]
    row = [g.r_net.sum()]
    for thr in (0.0, 0.0001, 0.0002, 0.0004):
        m = (g["dir"] == "LONG") & (g.slope_1h > thr) | (g["dir"] == "SHORT") & (g.slope_1h < -thr)
        row.append(g[m.fillna(False)].r_net.sum())
    print(f"  {int(y):<6}{row[0]:>+16.1f}{row[1]:>+16.1f}{row[2]:>+16.1f}{row[3]:>+16.1f}{row[4]:>+16.1f}")

print("\n=== то же: WR ===")
for thr in (0.0, 0.0002):
    m = (L & (s > thr)) | (S & (s < -thr))
    g = df[m.fillna(False)]
    print(f"  thr={100*thr:.2f}%: n={len(g)} WR={wr(g):.1f}% avg={g.r_net.mean():+.4f} | база WR={wr(df):.1f}% avg={df.r_net.mean():+.4f}")

print("\n=== портфель ПО ГОДАМ (риск 1%, 7 слотов, капитал не сбрасывается) ===")
for lab, m in [("raw", pd.Series(True, index=df.index)), ("ДЕПЛОЙ vwap", D),
               ("EMA3 1h thr0", (L & (s > 0)) | (S & (s < 0))),
               ("EMA3 1h thr0.02%", (L & (s > 0.0002)) | (S & (s < -0.0002))),
               ("EMA3 1h thr0.04%", (L & (s > 0.0004)) | (S & (s < -0.0004))),
               ("ДЕПЛОЙ+EMA3 1h 0.02%", D & ((df["dir"] != "LONG") | (s > 0.0002)))]:
    fin, mdd, n = pf(df[m.fillna(False)].copy())
    yr = {}
    for y in sorted(df.year.unique()):
        f, _, _ = pf(df[m.fillna(False) & (df.year >= y)].copy())
        yr[int(y)] = f
    print(f"  {lab:22} | весь ${fin:>10,.0f} MaxDD {mdd:>6.1f}% | по годам: " +
          " ".join(f"{y}:${v:,.0f}" for y, v in list(yr.items())[:7]))

print("\n=== 2024-26: связка с min_stop 0.5% ===")
g = df[(df.year >= 2024)].copy()
Lg = g["dir"] == "LONG"; Sg = g["dir"] == "SHORT"; sg = g.slope_1h
Dg = (Sg & (g.vd_conf <= 0)) | (Lg & (g.vd_conf >= 0))
for lab, m in [("EMA3 1h 0.02%", (Lg & (sg > 0.0002)) | (Sg & (sg < -0.0002))),
               ("EMA3 1h 0.02% + ms0.5%", ((Lg & (sg > 0.0002)) | (Sg & (sg < -0.0002))) & (g.sp >= 0.005)),
               ("ДЕПЛОЙ + ms0.5%", Dg & (g.sp >= 0.005)),
               ("EMA3 1h + ДЕПЛОЙ + ms0.5%", ((Lg & (sg > 0.0002)) | (Sg & (sg < -0.0002))) & Dg & (g.sp >= 0.005))]:
    fin, mdd, n = pf(g[m.fillna(False)].copy())
    print(f"  {lab:26} | взято {n:5d} | ${fin:>10,.0f} | MaxDD {mdd:>6.1f}%")
print("\nDONE")
