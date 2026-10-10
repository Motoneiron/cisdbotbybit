"""Финальная проверка: A) направление EMA3 1H + min_stop 0.5% — пороги и годы."""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3_r1.pkl")
tp = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
key = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = key(df); tp["k"] = key(tp)
mp = dict(zip(tp.k, tp["r_1_0"]))
df["r"] = [mp.get(x) for x in df.k]
df = df[df.r.notna()].copy()
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()


def wr(g):
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


L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; s = df.slope_h1; MS = df.sp >= 0.005
A = lambda t: (L & (s > t)) | (S & (s < -t))
print("=== A (направление EMA3 1H) + min_stop 0.5%: пороги ===")
print(f"  {'порог':>7} | {'2024-26: n  ΣR   $   DD':>32} | {'все годы: $  DD':>22}")
for thr in (0.0001, 0.0002, 0.0004, 0.001):
    g = df[A(thr).fillna(False) & MS]
    g4 = g[g.year >= 2024]
    f4, d4, n4 = pf(g4.copy()); f, d, _ = pf(g.copy())
    print(f"  {100*thr:6.2f}% | {n4:6d} {g4.r.sum():+7.0f} ${f4:>9,.0f} {d4:>6.1f}% | ${f:>12,.0f} {d:>6.1f}%")

print("\n=== итоговая связка (EMA3 1H >0.02% + min_stop 0.5%): по годам ===")
g = df[A(0.0002).fillna(False) & MS]
print(f"  {'год':6}{'взято':>8}{'WR':>8}{'avg':>10}{'ΣR':>10}{'портфель от $100':>20}")
for y, gy in df.groupby("year"):
    gf = g[g.year == y]
    f, _, _ = pf(g[g.year >= y].copy())
    print(f"  {int(y):<6}{len(gf):>8}{wr(gf):>7.1f}%{gf.r.mean():>+10.4f}{gf.r.sum():>+10.1f}{('$'+format(f,',.0f')):>20}")

print("\n=== сравнение вариантов для бота (2024-26, $100, 7 слотов, риск 1%) ===")
V = df.vd_conf
D = (S & (V <= 0)) | (L & (V >= 0))
opts = [
    ("1. как сейчас (raw)", pd.Series(True, index=df.index)),
    ("2. текущий vwap-гейт", D),
    ("3. EMA3 1H 0.02%", A(0.0002)),
    ("4. EMA3 1H 0.02% + min_stop 0.5%", A(0.0002) & MS),
    ("5. vwap-гейт + EMA3 1H 0.02%", D & A(0.0002)),
    ("6. vwap + EMA3 + min_stop 0.5%", D & A(0.0002) & MS),
    ("7. только min_stop 0.5%", MS),
]
for lab, m in opts:
    a = df[m.fillna(False)]
    b = a[a.year >= 2024]
    f2, d2, n2 = pf(b.copy())
    print(f"  {lab:34} | 2024-26: взято {n2:5d} WR={wr(b):.1f}% ΣR={b.r.sum():+7.0f} | ${f2:>9,.0f} | MaxDD {d2:>6.1f}%")
print("\nDONE")
