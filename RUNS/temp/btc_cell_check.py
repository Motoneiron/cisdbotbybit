"""Узкая клетка «BTC выстрелил только в нашу сторону» — устойчива ли она.

Прямое вето провалилось: при окне 12ч обратный сигнал BTC есть у 80–84% сделок, то есть
это не признак, а фон. Но эффект в первой проверке появился на ВЗАИМОИСКЛЮЧАЮЩИХ клетках:
«только согласный сигнал» против «только обратный». Здесь проверяем именно их, на узком
окне (30 минут — «около времени триггера», как и спрашивалось), с разбивкой по годам и
вневыборочно.

Запуск: python btc_cell_check.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from btc_leader import btc_index, count_before
from cross_tf import PROF, TPG, table


def main() -> None:
    bi = btc_index()
    tabs = {}
    for p in PROF:
        d = table(p)
        d = d[d.sym != "BTC"].copy()
        a = np.array(d.anchor, dtype="datetime64[ns]")
        for w in (0.5, 2.0):
            same = np.zeros(len(d), dtype=int)
            opp = np.zeros(len(d), dtype=int)
            for side in ("LONG", "SHORT"):
                m = (d.dir == side).to_numpy()
                same[m] = count_before(bi.get(side), a[m], w)
                opp[m] = count_before(bi.get("SHORT" if side == "LONG" else "LONG"), a[m], w)
            d[f"s{w}"], d[f"o{w}"] = same, opp
        tabs[p] = d

    for w in (0.5, 2.0):
        print(f"\nокно {w}ч: «только согласный BTC» против «только обратный»\n")
        for p in PROF:
            d = tabs[p]
            a_ = d[(d[f"s{w}"] > 0) & (d[f"o{w}"] == 0)]
            o_ = d[(d[f"s{w}"] == 0) & (d[f"o{w}"] > 0)]
            if len(o_) < 100:
                print(f"   {p}: обратных мало ({len(o_)})")
                continue
            diff = a_.net.mean() - o_.net.mean()
            se = np.sqrt(a_.net.var() / len(a_) + o_.net.var() / len(o_))
            ya = [(y, a_[a_.year == y].net.mean()) for y in sorted(a_.year.unique())
                  if len(a_[a_.year == y]) >= 30]
            yo = [(y, o_[o_.year == y].net.mean()) for y in sorted(o_.year.unique())
                  if len(o_[o_.year == y]) >= 30]
            ok = sum(1 for (y, va) in ya for (y2, vo) in yo if y == y2 and va > vo)
            tot = len({y for y, _ in ya} & {y for y, _ in yo})
            print(f"   {p}: согласный n={len(a_):5d} net={a_.net.mean():+.4f}"
                  f"±{a_.net.std()/np.sqrt(len(a_)):.4f} | обратный n={len(o_):5d} "
                  f"net={o_.net.mean():+.4f}±{o_.net.std()/np.sqrt(len(o_)):.4f}"
                  f" | Δ={diff:+.4f} (t={diff/se:+.1f}) согласный лучше в {ok}/{tot} лет")
            ia, oa = a_[a_.year <= 2023], a_[a_.year >= 2024]
            io, oo = o_[o_.year <= 2023], o_[o_.year >= 2024]
            if min(len(ia), len(oa), len(io), len(oo)) >= 50:
                print(f"       выборка: Δ={ia.net.mean()-io.net.mean():+.4f} | "
                      f"вне выборки: Δ={oa.net.mean()-oo.net.mean():+.4f} "
                      f"(n={len(oa)}/{len(oo)})")

    print("\nсравнение с базой: «только согласный» против всего потока альтов\n")
    for w in (0.5, 2.0):
        for p in PROF:
            d = tabs[p]
            g = d[(d[f"s{w}"] > 0) & (d[f"o{w}"] == 0)]
            diff = g.net.mean() - d.net.mean()
            print(f"   {p} окно {w}ч: клетка n={len(g):5d} ({len(g)/len(d)*100:4.1f}%) "
                  f"net={g.net.mean():+.4f} против базы {d.net.mean():+.4f} "
                  f"→ Δ={diff:+.4f}")
        print()
    pickle.dump(tabs, open(f"{TPG}/btc_cell.pkl", "wb"))


if __name__ == "__main__":
    main()
