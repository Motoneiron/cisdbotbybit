"""tf8-only: частота сделок (сигналы и взятые) — 10 пар, по годам.

Метрики:
  сигн/день   — все сигналы профиля, делённые на число дней периода
  взято/день  — сделки, реально открытые слот-симулятором (1 поз/пара, лимит 7)
  медиана/p90/макс в день, доля дней без сделок
Плюс tf7-only для сравнения.
"""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
tp = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
kk = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = kk(df); tp["k"] = kk(tp)
mp = dict(zip(tp.k, tp["r_1_0"]))
df["r"] = [mp.get(x) for x in df.k]
df = df[df.r.notna()].copy()
df["ts_fill"] = pd.to_datetime(df.ts_fill)
df["exit_ts"] = pd.to_datetime(df.exit_ts)
df["t_in"] = ((df.ts_fill - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((df.exit_ts - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1; V = df.vd_conf
E3 = ((L & (s > 0.0002)) | (S & (s < -0.0002))).fillna(False)
G = ((S & (V <= 0)) | (L & (V >= 0))).fillna(False)
MS = df.sp >= 0.005
VAR = {"без фильтров": pd.Series(True, index=df.index),
       "min_stop 0.5%": MS,
       "vwap-гейт + ms": G & MS,
       "EMA3 1H + ms": E3 & MS,
       "vwap+EMA3+ms": G & E3 & MS}


def taken(d, risk=0.01, start=100.0, maxpos=7):
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
        tk.append((tin, tout, sym, r)); heapq.heappush(hp, tout); pe[sym] = tout
    return pd.DataFrame(tk, columns=["t_in", "t_out", "sym", "r"])


print("Период потока: %s .. %s (%.0f дней)\n" % (df.ts_fill.min(), df.exit_ts.max(), (df.exit_ts.max() - df.ts_fill.min()).days))
for scope in ("tf8", "tf7"):
    sub = df[df.prof == scope]
    print(f"===== {scope} =====")
    print(f"  {'вариант':16} | {'сигналов':>8} {'сигн/день':>10} | {'взято':>7} {'взято/день':>11} | {'медиана':>8} {'p90':>5} {'макс':>5} {'дней с 0':>9}")
    for lab, m in VAR.items():
        g = sub[m.loc[sub.index]]
        d0 = (g.ts_fill.min(), g.exit_ts.max())
        days = (d0[1] - d0[0]).days or 1
        t = taken(g.copy())
        tk_day = t.assign(day=pd.to_datetime(t.t_in * 60, unit="s", origin="1970-01-01").dt.date).groupby("day").size()
        span_days = len(pd.date_range(g.ts_fill.min().date(), g.exit_ts.max().date(), freq="D"))
        print(f"  {lab:16} | {len(g):8d} {len(g)/days:10.2f} | {len(t):7d} {len(t)/days:11.2f} | "
              f"{tk_day.median():8.1f} {tk_day.quantile(0.9):5.1f} {tk_day.max():5d} {100*(span_days-len(tk_day))/span_days:8.0f}%")
    print()

print("===== tf8-only по годам (взято/день) =====")
sub = df[df.prof == "tf8"]
for y in sorted(df.year.unique()):
    g0 = sub[sub.year == y]
    days = (g0.exit_ts.max() - g0.ts_fill.min()).days or 1
    row = [f"  {int(y)}: дней {days:3d}"]
    for lab, m in VAR.items():
        g = g0[m.loc[g0.index]]
        t = taken(g.copy())
        row.append(f"{lab} {len(t)} ({len(t)/days:.2f}/д)")
    print(" | ".join(row))
print("\nDONE")
