"""EMA3 1H 0.02% + min_stop 0.5% — разбивка по профилям tf7 / tf8."""
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
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1; MS = df.sp >= 0.005
F = ((L & (s > 0.0002)) | (S & (s < -0.0002))) & MS


def w(g):
    x = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (x.outcome == "tp").mean() if len(x) else float("nan")


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
    for t, kk_, i in ev:
        tin, tout, r = tk[i]
        if kk_ == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * risk * r
            else:
                rm[i] = bal * risk
        cur.append((t, bal))
    ss = pd.Series([c[1] for c in cur])
    return bal, float(((ss - ss.cummax()) / ss.cummax()).min() * 100), len(tk)


print("=== ΣR / WR / avg по профилям: база vs EMA3 1H 0.02% + ms0.5% ===")
for prof in ("tf7", "tf8"):
    print(f"\n-- {prof} --")
    for tag, sub in (("все годы", df[df.prof == prof]), ("2024-26", df[(df.prof == prof) & (df.year >= 2024)])):
        b = sub
        f = sub[F.loc[sub.index].fillna(False)]
        print(f"  {tag:9} | база: n={len(b):5d} WR={w(b):5.1f}% avg={b.r.mean():+.4f} ΣR={b.r.sum():+8.1f}"
              f" | фильтр: n={len(f):5d} WR={w(f):5.1f}% avg={f.r.mean():+.4f} ΣR={f.r.sum():+8.1f} (оставлено {100*len(f)/max(len(b),1):.0f}%)")

print("\n=== по ногам (2024-26) ===")
for prof in ("tf7", "tf8"):
    g = df[(df.prof == prof) & (df.year >= 2024)]
    for lab, m in (("LONG", g["dir"] == "LONG"), ("SHORT", g["dir"] == "SHORT")):
        b = g[m]; f = b[F.loc[b.index].fillna(False)]
        print(f"  {prof} {lab:5} | база n={len(b):5d} WR={w(b):5.1f}% avg={b.r.mean():+.4f} ΣR={b.r.sum():+7.1f}"
              f" | фильтр n={len(f):4d} WR={w(f):5.1f}% avg={f.r.mean():+.4f} ΣR={f.r.sum():+7.1f}")

print("\n=== портфель по годам: только tf7 vs только tf8 (фильтр), 7 слотов, $100 ===")
for prof in ("tf7", "tf8"):
    for tag, sub in (("фильтр", df[F.fillna(False) & (df.prof == prof)]), ("база", df[df.prof == prof])):
        out = []
        for y in sorted(df.year.unique()):
            f, _, _ = pf(sub[sub.year >= y].copy())
            out.append(f"{int(y)}:${f:,.0f}")
        fin, dd, n = pf(sub.copy())
        print(f"  {prof} {tag:6} весь ${fin:>11,.0f} ({dd:>6.1f}%) | " + " ".join(out))

print("\n=== вместе (обо профиля) с фильтром: кто сколько даёт в ΣR ===")
f = df[F.fillna(False)]
for prof in ("tf7", "tf8"):
    sub = f[f.prof == prof]
    print(f"  {prof}: сделок {len(sub)} ({100*len(sub)/len(f):.0f}% потока фильтра), ΣR {sub.r.sum():+.1f} ({100*sub.r.sum()/f.r.sum():.0f}% суммы)")
t7 = f[f.prof == "tf7"]; t8 = f[f.prof == "tf8"]
print(f"  2024-26: tf7 ΣR {t7[t7.year>=2024].r.sum():+.1f} | tf8 ΣR {t8[t8.year>=2024].r.sum():+.1f}")
print("\nDONE")
