# -*- coding: utf-8 -*-
"""Перепроверка разреза «свип→конфирм» (dt_sw) на родных датасетах tf1-серии.
Только чтение. Вывод в консоль (для сводки).
"""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def block(name, d):
    def line(tag, g):
        a = g[g.outcome.isin(["tp", "sl"])]
        wr = 100 * (a.outcome == "tp").mean() if len(a) else float("nan")
        print(f"  {tag:26s} n={len(g):4d} WR={wr:5.1f}% avgR={g.r.mean():+.3f} SR={g.r.sum():+.1f}")
    print(f"### {name}")
    line("ALL", d)
    line("<2ч", d[d.dt_sw < 120])
    line(">=2ч", d[d.dt_sw >= 120])
    for lo, hi, tag in [(0, 30, "0-30м"), (30, 60, "30-60м"), (60, 120, "60-120м"),
                        (120, 240, "2-4ч"), (240, 480, "4-8ч"), (480, 10**9, "8ч+")]:
        g = d[(d.dt_sw >= lo) & (d.dt_sw < hi)]
        if len(g):
            line(tag, g)
    print()


def cuts(name, d):
    print(f"### {name}: кумулятивные отсечения dt_sw >= X")
    for x in [90, 105, 120, 135, 150, 165, 180, 240]:
        g = d[d.dt_sw >= x]
        print(f"  >= {x:3d}м: n={len(g):4d} SR={g.r.sum():+7.1f} avgR={g.r.mean():+.3f}")
    print()


def main():
    d822 = pd.read_pickle(f"{BASE}/stopt_df.pkl")
    d822["year"] = pd.to_datetime(d822["scan"]).dt.year
    d1007 = pd.read_pickle(f"{BASE}/stopt_df_alloff_l1h.pkl")
    d1007["year"] = pd.to_datetime(d1007["scan"]).dt.year
    d998 = pd.read_pickle(f"{BASE}/stopt_v2_10pairs_final.pkl")
    # dt_sw: восстановить из cbt - tbt (новые пары пустые)
    d998["dt_sw"] = pd.to_datetime(d998["cbt"]) - pd.to_datetime(d998["tbt"])
    d998["dt_sw"] = d998["dt_sw"].dt.total_seconds() / 60.0

    block("stopt_df (822, 6 пар, v1: ATR, до фильтра)", d822)
    block("stopt_df_alloff_l1h (1007, 6 пар, noatr, до фильтра)", d1007)
    cuts("822", d822)
    cuts("1007", d1007)

    block("stopt_v2_10pairs_final (998, 10 пар, >=2ч)", d998)

    print("### 822: <2ч vs >=2ч по годам")
    for y in (2024, 2025, 2026):
        g = d822[d822.year == y]
        a, b = g[g.dt_sw >= 120], g[g.dt_sw < 120]
        if len(a) and len(b):
            print(f"  {y}: <2ч n={len(b):3d} avgR={b.r.mean():+.3f} | >=2ч n={len(a):3d} avgR={a.r.mean():+.3f}")
    print()
    print("### 1007: <2ч vs >=2ч по годам")
    for y in (2024, 2025, 2026):
        g = d1007[d1007.year == y]
        a, b = g[g.dt_sw >= 120], g[g.dt_sw < 120]
        if len(a) and len(b):
            print(f"  {y}: <2ч n={len(b):3d} avgR={b.r.mean():+.3f} | >=2ч n={len(a):3d} avgR={a.r.mean():+.3f}")


if __name__ == "__main__":
    main()
