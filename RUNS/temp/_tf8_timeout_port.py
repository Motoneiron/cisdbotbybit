"""Портфель по горизонтам удержания tf8 + проверка дня недели на половинах."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
d = pd.read_pickle(f"{BASE}/stream_tf8_timeout.pkl")
d["ts_fill"] = pd.to_datetime(d.ts_fill)
d = d[d["r_6"].notna()].copy()
d["t_in"] = ((d.ts_fill - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")


def pf(sub, rcol, h, risk=0.01, start=100.0, maxpos=7):
    g = sub.copy()
    # длительность позиции: до первого касания TP/SL либо до горизонта
    tmin = np.minimum(g.t_tp_min.fillna(1e9), g.t_sl_min.fillna(1e9))
    tmin = np.minimum(tmin, h * 60)
    g["t_out"] = g.t_in + tmin.fillna(h * 60).astype("int64")
    it = list(zip(g.t_in, g.t_out, g.sym, g[rcol].astype(float)))
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


g = d[d.sp >= 0.005]
print("=== tf8 + min_stop 0.5%: портфель по горизонтам ($100, 7 слотов) ===")
print(f"  {'гориз':>5} | {'все годы: взято / $ / MaxDD':>34} | {'2024-26: взято / $ / MaxDD':>32} | {'ΣR сигн.':>9}")
for h in (6, 9, 12, 18, 24, 36, 48):
    f1, d1, n1 = pf(g, f"r_{h}", h)
    g24 = g[g.year >= 2024]
    f2, d2, n2 = pf(g24, f"r_{h}", h)
    print(f"  {h:4d}ч | {n1:6d} ${f1:>13,.0f} {d1:>6.1f}% | {n2:6d} ${f2:>12,.0f} {d2:>6.1f}% | {g[f'r_{h}'].sum():+9.1f}")

print("\n=== день недели: ΔΣR (6ч→24ч) по половинам истории ===")
d["dow"] = d.ts_fill.dt.dayofweek
mid = d.ts_fill.quantile(0.5)
for nm, sub in (("1-я половина", d[d.ts_fill < mid]), ("2-я половина", d[d.ts_fill >= mid])):
    dd = sub.groupby("dow").apply(lambda x: x["r_24"].sum() - x["r_6"].sum())
    print(f"  {nm}: " + " | ".join(f"{'ПнВтСрЧтПтСбВс'[i]}: {v:+.0f}" for i, v in dd.items()))
print("\n=== средняя занятость слотов по горизонтам ===")
for h in (6, 12, 24):
    tt = np.minimum(np.minimum(g.t_tp_min.fillna(1e9), g.t_sl_min.fillna(1e9)), h * 60).fillna(h * 60)
    days = (g.ts_fill.max() - g.ts_fill.min()).days or 1
    print(f"  {h:2d}ч: позиций/день {len(g)/days:.2f} × средняя длительность {tt.mean()/60:.1f}ч ({100*tt.mean()/60/24:.1f}% времени) → занято слотов ≈ {len(g)/days*tt.mean()/60/24:.2f}")
print("\nDONE")
