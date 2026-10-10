"""Скученность: это самостоятельный эффект или переодетая ширина стопа?

Проверки:
  1. связь crowd с шириной стопа и волатильностью — если при crowd > 0 стопы
     систематически уже, то «эффект» это просто комиссия, уже известная;
  2. эффект внутри полос по стопу — если он держится в каждой полосе, он свой;
  3. устойчивость по годам и по парам: разница net(crowd≤0) − net(crowd>0);
  4. честный вневыборочный тест: правило фиксируем на 2020–2023, считаем на 2024–2026.

Запуск: python crowding_check.py
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from cross_tf import PROF, TPG

BANDS = [(0, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 99)]


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_crowd.pkl", "rb"))

    print("1. Средняя ширина стопа и доля SL по скученности\n")
    print("   crowd " + "".join(p.rjust(22) for p in PROF))
    for c in (-2, -1, 0, 1, 2):
        line = f"   {c:+d}    "
        for p in PROF:
            g = tabs[p][tabs[p].crowd == c]
            line += (f"стоп {g.stop_pct.mean():.2f}% SL {g.is_sl.mean():.3f}".rjust(22)
                     if len(g) >= 100 else "—".rjust(22))
        print(line)

    print("\n2. Эффект внутри полос по ширине стопа: net(crowd≤0) − net(crowd>0)\n")
    print("   полоса стопа  " + "".join(p.rjust(20) for p in PROF))
    for lo, hi in BANDS:
        line = f"   {lo:.1f}–{hi if hi < 90 else 99:.0f}%".ljust(17)
        for p in PROF:
            d = tabs[p]
            b = d[(d.stop_pct >= lo) & (d.stop_pct < hi)]
            a_, z_ = b[b.crowd <= 0], b[b.crowd > 0]
            if len(a_) < 100 or len(z_) < 100:
                line += "—".rjust(20)
                continue
            diff = a_.net.mean() - z_.net.mean()
            se = np.sqrt(a_.net.var() / len(a_) + z_.net.var() / len(z_))
            line += f"{diff:+.4f} (t={diff/se:+.1f})".rjust(20)
        print(line)

    print("\n3. Разница net(crowd≤0) − net(crowd>0) по годам\n")
    print("   профиль " + "".join(str(y).rjust(10) for y in range(2020, 2027)) + "   плюс-лет")
    for p in PROF:
        d, line, pos = tabs[p], f"   {p:8s}", 0
        for y in range(2020, 2027):
            g = d[d.year == y]
            a_, z_ = g[g.crowd <= 0], g[g.crowd > 0]
            if len(a_) < 50 or len(z_) < 50:
                line += "—".rjust(10)
                continue
            diff = a_.net.mean() - z_.net.mean()
            pos += diff > 0
            line += f"{diff:+.4f}".rjust(10)
        print(line + f"   {pos}/7")

    print("\n4. Вневыборочно: правило подобрано на 2020–2023, проверено на 2024–2026\n")
    for p in PROF:
        d = tabs[p]
        ins, oos = d[d.year <= 2023], d[d.year >= 2024]
        for lbl, rule in (
            ("crowd≤0", lambda x: x.crowd <= 0),
            ("crowd≤0 & SHORT", lambda x: (x.crowd <= 0) & (x.dir == "SHORT")),
            ("crowd≤0 & SHORT & стоп≥2.5%",
             lambda x: (x.crowd <= 0) & (x.dir == "SHORT") & (x.stop_pct >= 2.5)),
        ):
            gi, go = ins[rule(ins)], oos[rule(oos)]
            if len(gi) < 100 or len(go) < 100:
                continue
            print(f"  {p} {lbl:28s} in={gi.net.mean():+.4f} (n={len(gi):5d}) "
                  f"out={go.net.mean():+.4f} (n={len(go):5d})")
        print()

    print("5. tf2 лучшая ячейка по парам (crowd≤0 & SHORT & стоп≥2.5%)\n")
    d = tabs["tf2"]
    g = d[(d.crowd <= 0) & (d.dir == "SHORT") & (d.stop_pct >= 2.5)]
    for sym, gs in g.groupby("sym"):
        print(f"   {sym:5s} n={len(gs):4d} net={gs.net.mean():+.4f} SL={gs.is_sl.mean():.3f}")


if __name__ == "__main__":
    main()
