"""Условный таймаут tf8: зависит ли оптимальный горизонт от признаков сетапа.

Для каждого признака: бакеты по квантилям → ΣR при 6/12/24ч и Δ(6→24).
Затем честный walk-forward: правило «горизонт по бакету» выбираем на 1-й половине,
проверяем на 2-й, сравниваем со статичными 6ч и 24ч на той же 2-й половине.
"""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
d = pd.read_pickle(f"{BASE}/stream_tf8_timeout.pkl")
d = d[d["r_6"].notna() & (d.sp >= 0.005)].copy()
d["ts_fill"] = pd.to_datetime(d.ts_fill)
d["absslope"] = d.slope_h1.abs()
FEATS = {"sp": "стоп, доля", "fill_wait_min": "ждал лимитку, мин", "vd_conf": "vwap-откл (conf)",
         "of1_conf": "CVD-имбаланс", "el_frac": "Эллиотт frac", "slope_h1": "наклон EMA3 1H",
         "absslope": "|наклон EMA3|"}
HS = [6, 12, 24]

print(f"=== ΔΣR(6→24) по бакетам признаков (tf8+ms0.5%, n={len(d)}) ===")
for f, rname in FEATS.items():
    x = d[d[f].notna()].copy()
    if x[f].nunique() < 6:
        continue
    x["b"] = pd.qcut(x[f], 5, labels=False, duplicates="drop")
    print(f"\n-- {rname} ({f}) --")
    print(f"   {'бакет':>22} | {'n':>6} | {'ΣR 6ч':>8} {'ΣR 12ч':>8} {'ΣR 24ч':>8} | {'Δ 6→24':>8} | {'Δ 6→12':>8}")
    for b, g in x.groupby("b"):
        print(f"   [{g[f].min():>9.4f}..{g[f].max():>9.4f}] | {len(g):6d} | {g['r_6'].sum():+8.1f} {g['r_12'].sum():+8.1f} {g['r_24'].sum():+8.1f} "
              f"| {g['r_24'].sum()-g['r_6'].sum():+8.1f} | {g['r_12'].sum()-g['r_6'].sum():+8.1f}")

mid = d.ts_fill.quantile(0.5)
tr, te = d[d.ts_fill < mid], d[d.ts_fill >= mid]
print(f"\n=== WALK-FORWARD (выбор на 1-й половине n={len(tr)}, проверка на 2-й n={len(te)}) ===")
print(f"  {'признак':>20} | {'2-я половина: статичные 6ч / 12ч / 24ч':>40} | {'условный (по бакету)':>22}")
for f, rname in FEATS.items():
    x = d[d[f].notna()].copy()
    if x[f].nunique() < 6:
        continue
    x["b"] = pd.qcut(x[f], 5, labels=False, duplicates="drop")
    xtr = x[x.ts_fill < mid]; xte = x[x.ts_fill >= mid]
    best = {}
    for b, g in xtr.groupby("b"):
        sums = {h: g[f"r_{h}"].sum() for h in HS}
        best[b] = max(sums, key=sums.get)
    r6 = xte["r_6"].sum(); r12 = xte["r_12"].sum(); r24 = xte["r_24"].sum()
    cond = sum(xte[xte.b == b][f"r_{h}"].sum() for b, h in best.items())
    print(f"  {rname:20} | {r6:+8.1f} / {r12:+8.1f} / {r24:+8.1f} | {cond:+8.1f}  (правило: " +
          ", ".join(f"{int(b)}→{best[b]}ч" for b in sorted(best)) + ")")
print("\nDONE")
