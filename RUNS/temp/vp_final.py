"""Дозакрытие volume profile: block_share по явным бакетам и судьба клетки tf2 SHORT.

Две недоделки предыдущего прогона.

1. block_share (доля плотных уровней на пути от входа к тейку) двухвершинный: 43–45%
   значений ровно 1.0 и около четверти ровно 0. Квинтили на таком распределении
   схлопываются в один бакет, поэтому там и вышло Δ=+0.000 — признак не был проверен.
   Здесь явные бакеты.

2. Единственная клетка, пережившая контроль на направление И ширину стопа, — tf2 SHORT
   с высоким va_pos (вход в верхней части зоны стоимости). Все предыдущие находки на tf2
   умирали вне выборки, поэтому проверяем сразу по годам и на 2024–2026.

Запуск: python vp_final.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG

BUCKETS = [(-0.01, 0.001, "ровно 0"), (0.001, 0.5, "0–0.5"),
           (0.5, 0.999, "0.5–1"), (0.999, 1.01, "ровно 1")]


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_vp.pkl", "rb"))

    print("\n1. block_share по явным бакетам (net R)\n")
    for p in PROF:
        d = tabs[p][tabs[p].block_share.notna()]
        print(f"   {p} (база net={d.net.mean():+.4f}):")
        for lo, hi, nm in BUCKETS:
            g = d[(d.block_share > lo) & (d.block_share <= hi)]
            if len(g) < 200:
                continue
            print(f"     {nm:8s} n={len(g):6d} net={g.net.mean():+.4f}"
                  f"±{g.net.std()/np.sqrt(len(g)):.4f} SL={g.is_sl.mean():.3f}")
        a = d[d.block_share >= 0.999]
        b = d[d.block_share <= 0.001]
        if len(a) > 200 and len(b) > 200:
            diff = b.net.mean() - a.net.mean()
            se = np.sqrt(a.net.var() / len(a) + b.net.var() / len(b))
            print(f"     путь свободен минус путь забит: {diff:+.4f} (t={diff/se:+.1f})")

    print("\n2. Клетка tf2 SHORT с высоким va_pos: по годам и вне выборки\n")
    d = tabs["tf2"]
    d = d[(d.dir == "SHORT") & d.va_pos.notna()]
    for th in (0.6, 0.8, 1.0):
        g = d[d.va_pos >= th]
        if len(g) < 150:
            continue
        ins, oos = g[g.year <= 2023], g[g.year >= 2024]
        years = [(y, g[g.year == y].net.mean()) for y in sorted(g.year.unique())
                 if len(g[g.year == y]) >= 25]
        pos = sum(1 for _, v in years if v > 0)
        print(f"   va_pos≥{th}: n={len(g):4d} net={g.net.mean():+.4f}"
              f"±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/{len(years)} "
              f"| выборка {ins.net.mean():+.4f} (n={len(ins)}) "
              f"| вне выборки {oos.net.mean():+.4f} (n={len(oos)})")
        print("     по годам: " + " ".join(f"{y}:{v:+.3f}" for y, v in years))

    print("\n3. Та же клетка с широким стопом (стержень tf2 из прошлого разбора)\n")
    for th_v, th_s in ((0.6, 2.5), (0.8, 2.5), (0.6, 1.5)):
        g = d[(d.va_pos >= th_v) & (d.stop_pct >= th_s)]
        if len(g) < 100:
            continue
        ins, oos = g[g.year <= 2023], g[g.year >= 2024]
        years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                 if len(g[g.year == y]) >= 20]
        pos = sum(1 for v in years if v > 0)
        print(f"   va_pos≥{th_v} стоп≥{th_s}%: n={len(g):4d} net={g.net.mean():+.4f}"
              f"±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/{len(years)} "
              f"| выборка {ins.net.mean():+.4f} | вне выборки {oos.net.mean():+.4f} "
              f"(n={len(oos)})")


if __name__ == "__main__":
    main()
