"""va_pos: собственный признак или переодетое направление сделки.

Градиент va_pos и poc_atr одного знака на всех четырёх профилях (t до +2.3) — это первый
такой случай после ширины стопа. Но оба признака НЕ приведены к направлению: va_pos — где
вход внутри зоны стоимости, poc_atr — вход выше или ниже самого объёмного уровня. У шорта
вход после снятия максимумов почти всегда высоко в профиле, у лонга — низко. А шорты у нас
лучше лонгов на всех профилях. То есть градиент может быть просто направлением.

Проверка: те же квинтили ОТДЕЛЬНО внутри лонгов и внутри шортов. Если признак свой —
градиент сохранится в обеих группах.

Запуск: python vp_direction_check.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG


def grad(d: pd.DataFrame, col: str) -> str:
    d = d[d[col].notna()]
    if len(d) < 400:
        return "—".rjust(15)
    b = pd.qcut(d[col], 5, labels=False, duplicates="drop")
    lo, hi = d[b == b.min()], d[b == b.max()]
    diff = hi.net.mean() - lo.net.mean()
    se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
    return f"{diff:+.3f}({diff/se:+.1f})".rjust(15)


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_vp.pkl", "rb"))

    print("\n1. Доля шортов по квинтилям va_pos (проверка подмены направлением)\n")
    for p in PROF:
        d = tabs[p][tabs[p].va_pos.notna()]
        b = pd.qcut(d.va_pos, 5, labels=False, duplicates="drop")
        sh = [(d[b == k].dir == "SHORT").mean() for k in sorted(pd.unique(b))]
        print(f"   {p}: " + " ".join(f"{v*100:5.1f}%" for v in sh)
              + f"   (корр va_pos с шортом {d.va_pos.corr((d.dir == 'SHORT').astype(float)):+.3f})")

    print("\n2. Градиент ВНУТРИ направления (Δnet Q5−Q1, t)\n")
    for col in ("va_pos", "poc_atr", "va_width_atr"):
        print(f"   {col}:")
        print("     " + "группа".ljust(12) + "".join(p.rjust(15) for p in PROF))
        for nm, sel in (("все", None), ("только LONG", "LONG"), ("только SHORT", "SHORT")):
            line = "     " + nm.ljust(12)
            for p in PROF:
                d = tabs[p]
                line += grad(d if sel is None else d[d.dir == sel], col)
            print(line)
        print()

    print("3. block_share: не выродился ли признак\n")
    for p in PROF:
        s = tabs[p].block_share.dropna()
        print(f"   {p}: n={len(s)} уникальных значений={s.nunique()} "
              f"доля ровно 1.0 = {(s >= 0.999).mean()*100:.1f}% "
              f"квартили {s.quantile(0.25):.3f}/{s.quantile(0.5):.3f}/{s.quantile(0.75):.3f}")

    print("\n4. Что остаётся, если сравнивать va_pos внутри направления И ширины стопа\n")
    for p in PROF:
        d = tabs[p][tabs[p].va_pos.notna()]
        out = []
        for dr in ("SHORT", "LONG"):
            g = d[d.dir == dr]
            sb = pd.qcut(g.stop_pct, 3, labels=False, duplicates="drop")
            sig = 0
            for k in range(3):
                gg = g[sb == k]
                if len(gg) < 400:
                    continue
                vb = pd.qcut(gg.va_pos, 5, labels=False, duplicates="drop")
                lo, hi = gg[vb == vb.min()], gg[vb == vb.max()]
                diff = hi.net.mean() - lo.net.mean()
                se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
                if se > 0 and abs(diff / se) >= 2:
                    sig += 1
            out.append(f"{dr} значимых клеток {sig}/3")
        print(f"   {p}: " + ", ".join(out))


if __name__ == "__main__":
    main()
