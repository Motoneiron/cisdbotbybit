"""Скученность ТФ: согласие профилей между собой — плохой признак.

Из cross_tf2.py: в 7 случаях из 8 (цель × источник) сделки идут ХУЖЕ, когда на
другом профиле в этот момент открыта позиция того же направления, и ЛУЧШЕ, когда
противоположного. Механически объяснимо: одновременный разворотный сетап на
нескольких ТФ означает, что все разом контрят один и тот же сильный ход — а
контртренд на этих данных уже показал минус (см. REPORT_CEILING, раздел 11).

Здесь считаем скученность одним числом и проверяем как правило отбора:

  crowd = (сколько других профилей держат позицию В ТУ ЖЕ сторону)
        − (сколько держат в противоположную)

Всё причинно: учитываются только позиции, открытые не позже нашего якоря.

Запуск: python crowding.py
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from cross_tf import PROF, TPG, table
from cross_tf2 import HOLD_H


def add_crowd(tabs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    for target, d in tabs.items():
        d = d.copy()
        same = np.zeros(len(d), dtype=int)
        opp = np.zeros(len(d), dtype=int)
        for src, s in tabs.items():
            if src == target:
                continue
            hold = np.timedelta64(HOLD_H[src], "h")
            iv = {k: np.sort(np.array(g.anchor, dtype="datetime64[ns]"))
                  for k, g in s.groupby(["sym", "dir"])}
            for i, (sym, dr, a) in enumerate(zip(d.sym, d.dir, d.anchor)):
                a64 = np.datetime64(a)
                o = "SHORT" if dr == "LONG" else "LONG"
                for side, dst in ((dr, same), (o, opp)):
                    arr = iv.get((sym, side))
                    if arr is None:
                        continue
                    lo = np.searchsorted(arr, a64 - hold, "right")
                    hi = np.searchsorted(arr, a64, "right")
                    if hi > lo:
                        dst[i] += 1
        d["n_same"], d["n_opp"] = same, opp
        d["crowd"] = same - opp
        out[target] = d
    return out


def by_crowd(tabs: dict[str, pd.DataFrame]) -> None:
    print("net R по скученности (crowd = согласных профилей − противоположных)\n")
    print("   crowd " + "".join(p.rjust(24) for p in PROF))
    for c in (-3, -2, -1, 0, 1, 2, 3):
        line = f"   {c:+d}    "
        for p in PROF:
            g = tabs[p][tabs[p].crowd == c]
            if len(g) < 100:
                line += f"n={len(g)}".rjust(24)
                continue
            se = g.net.std() / np.sqrt(len(g))
            line += f"{g.net.mean():+.4f}±{se:.3f} n={len(g):<5d}".rjust(24)
        print(line)

    print("\nправило «не брать, если crowd > 0» (то есть согласных больше):\n")
    for p in PROF:
        d = tabs[p]
        g = d[d.crowd <= 0]
        pos = sum(1 for y in sorted(g.year.unique()) if g[g.year == y].net.mean() > 0)
        se = g.net.std() / np.sqrt(len(g))
        drop = d[d.crowd > 0]
        print(f"  {p}: остаётся {len(g):5d} из {len(d):5d} ({len(g)/len(d)*100:.0f}%) "
              f"net {d.net.mean():+.4f} → {g.net.mean():+.4f}±{se:.4f} "
              f"лет={pos}/7 | отброшено n={len(drop)} net={drop.net.mean():+.4f}")

    print("\nто же + SHORT + стоп ≥ 2.5%:\n")
    for p in PROF:
        d = tabs[p]
        g = d[(d.crowd <= 0) & (d.dir == "SHORT") & (d.stop_pct >= 2.5)]
        if len(g) < 100:
            print(f"  {p}: мало ({len(g)})")
            continue
        pos = sum(1 for y in sorted(g.year.unique()) if g[g.year == y].net.mean() > 0)
        se = g.net.std() / np.sqrt(len(g))
        print(f"  {p}: n={len(g):5d} net={g.net.mean():+.4f}±{se:.4f} лет={pos}/7 "
              f"SL={g.is_sl.mean():.3f} mfe−mae={g.mfe.mean()-g.mae.mean():+.3f}")

    print("\nустойчивость правила crowd≤0 по годам (net R):\n")
    print("   профиль " + "".join(str(y).rjust(10) for y in range(2020, 2027)))
    for p in PROF:
        line = f"   {p:8s}"
        d = tabs[p][tabs[p].crowd <= 0]
        for y in range(2020, 2027):
            g = d[d.year == y]
            line += (f"{g.net.mean():+.4f}".rjust(10) if len(g) >= 50 else "—".rjust(10))
        print(line)


if __name__ == "__main__":
    try:
        tabs = pickle.load(open(f"{TPG}/cross_tf_tabs.pkl", "rb"))
    except FileNotFoundError:
        tabs = {p: table(p) for p in PROF}
    t = add_crowd(tabs)
    by_crowd(t)
    pickle.dump(t, open(f"{TPG}/cross_tf_crowd.pkl", "wb"))
