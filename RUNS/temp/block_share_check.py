"""block_share: объём на пути к тейку. Единственный признак с одним знаком на 4 профилях.

Смысл: берём профиль объёма за последние 150 старших баров и смотрим коридор от входа до
тейка 1R. block_share — какая доля объёма в этом коридоре лежит на «плотных» уровнях
(объём больше 1.5 медианы). Ноль = путь к тейку пустой, единица = путь забит.

Результат первого замера («путь свободен» минус «путь забит»): tf0 +0.018 (t=2.0),
tf1 +0.035 (t=2.9), tf2 +0.033 (t=1.4), tf8 +0.034 (t=2.3). Знак один, механика
осмысленна (объём над головой мешает дойти до цели), признак не зависит от направления.

Ловушки, на которых сегодня погибли остальные признаки, проверяем сразу все:
  1. ширина стопа — эффект внутри её квинтилей;
  2. направление сделки;
  3. устойчивость по годам и на 2024–2026 (правило не настраивается, порог структурный:
     ноль против единицы);
  4. не тавтология ли: длина коридора зависит от ширины стопа, а число «плотных» уровней —
     от того, сколько бинов в коридор попало.

Запуск: python block_share_check.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG


def pair(d: pd.DataFrame) -> tuple[float, float, int, int]:
    a, b = d[d.block_share <= 0.001], d[d.block_share >= 0.999]
    if len(a) < 80 or len(b) < 80:
        return np.nan, np.nan, len(a), len(b)
    diff = a.net.mean() - b.net.mean()
    se = np.sqrt(a.net.var() / len(a) + b.net.var() / len(b))
    return diff, diff / se if se > 0 else np.nan, len(a), len(b)


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_vp.pkl", "rb"))
    for p in PROF:
        tabs[p] = tabs[p][tabs[p].block_share.notna()].copy()

    print("\n1. Связь с шириной стопа и волатильностью\n")
    for p in PROF:
        d = tabs[p]
        a, b = d[d.block_share <= 0.001], d[d.block_share >= 0.999]
        print(f"   {p}: путь пустой стоп {a.stop_pct.median():.2f}% / забит "
              f"{b.stop_pct.median():.2f}%  | зона стоимости в ATR "
              f"{a.va_width_atr.median():.1f} / {b.va_width_atr.median():.1f}"
              f"  | корр block_share↔стоп {d.block_share.corr(d.stop_pct):+.3f}")

    print("\n2. Эффект ВНУТРИ квинтилей ширины стопа (net R: пустой минус забитый)\n")
    print("   профиль" + "".join(f"Q{i+1} стопа".rjust(16) for i in range(5)))
    for p in PROF:
        d = tabs[p]
        b = pd.qcut(d.stop_pct, 5, labels=False, duplicates="drop")
        line = f"   {p:8s}"
        for k in range(5):
            diff, t, na, nb = pair(d[b == k])
            line += ("—".rjust(16) if np.isnan(diff)
                     else f"{diff:+.3f}({t:+.1f})".rjust(16))
        print(line)

    print("\n3. Эффект внутри направления\n")
    print("   профиль" + "".join(nm.rjust(18) for nm in ("все", "SHORT", "LONG")))
    for p in PROF:
        d = tabs[p]
        line = f"   {p:8s}"
        for sel in (None, "SHORT", "LONG"):
            diff, t, na, nb = pair(d if sel is None else d[d.dir == sel])
            line += ("—".rjust(18) if np.isnan(diff)
                     else f"{diff:+.3f}({t:+.1f})".rjust(18))
        print(line)

    print("\n4. По годам (net R: пустой путь / забитый путь)\n")
    for p in PROF:
        d = tabs[p]
        print(f"   {p}:")
        ok = 0
        tot = 0
        for y in sorted(d.year.unique()):
            g = d[d.year == y]
            a, b = g[g.block_share <= 0.001], g[g.block_share >= 0.999]
            if len(a) < 60 or len(b) < 60:
                continue
            tot += 1
            ok += int(a.net.mean() > b.net.mean())
            print(f"     {y}: {a.net.mean():+.4f} против {b.net.mean():+.4f}"
                  f"  (n={len(a)}/{len(b)})")
        print(f"     пустой путь лучше в {ok}/{tot} лет")

    print("\n5. Вне выборки (правило структурное, порог не настраивался)\n")
    for p in PROF:
        d = tabs[p]
        ins, oos = d[d.year <= 2023], d[d.year >= 2024]
        di, ti, _, _ = pair(ins)
        do, to, na, nb = pair(oos)
        print(f"   {p}: выборка Δ={di:+.4f} (t={ti:+.1f}) | "
              f"вне выборки Δ={do:+.4f} (t={to:+.1f}, n={na}/{nb})")

    print("\n6. Пустой путь + широкий стоп: насколько близко к нулю\n")
    for p in PROF:
        d = tabs[p]
        print(f"   {p} (база {d.net.mean():+.4f}):")
        for th in (0.0, 1.0, 1.5, 2.5):
            g = d[(d.block_share <= 0.001) & (d.stop_pct >= th)]
            if len(g) < 200:
                continue
            years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 25]
            pos = sum(1 for v in years if v > 0)
            oos = g[g.year >= 2024]
            print(f"     стоп≥{th}%: n={len(g):5d} ({len(g)/len(d)*100:4.1f}%) "
                  f"net={g.net.mean():+.4f}±{g.net.std()/np.sqrt(len(g)):.4f} "
                  f"лет={pos}/{len(years)} вне выборки={oos.net.mean():+.4f} (n={len(oos)})")


if __name__ == "__main__":
    main()
