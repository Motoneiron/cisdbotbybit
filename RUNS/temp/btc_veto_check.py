"""Две зацепки из проверки битка: выдерживают ли они контроль на ширину стопа.

Из `btc_leader.py` вышли два признака с ОДИНАКОВЫМ знаком на всех четырёх профилях:

  A. «вето битка»: если в окне перед входом был сигнал BTC в ОБРАТНУЮ сторону, сделка
     хуже (tf1 −0.222 против −0.080; tf8 −0.140 против −0.072; tf2 −0.146 против −0.020);
  B. «кластер»: чем больше сигналов той же стороны по всем парам рядом, тем лучше
     (верхний квартиль лучше нижнего на всех четырёх профилях).

Обе могут быть переодетой шириной стопа: много сигналов = волатильный участок = широкие
стопы = меньше доля комиссии. Ровно так развалился «рывок перед входом». Поэтому здесь:
связь с шириной стопа, эффект ВНУТРИ квинтилей стопа, устойчивость по годам и
вневыборочно.

Запуск: python btc_veto_check.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from btc_leader import all_index, btc_index, count_before
from cross_tf import PROF, TPG, table

W_VETO = 12.0
W_CLU = 6.0


def prep(tabs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    bi, ai = btc_index(), all_index()
    out = {}
    for p, d in tabs.items():
        d = d[d.sym != "BTC"].copy()
        a = np.array(d.anchor, dtype="datetime64[ns]")
        same = np.zeros(len(d), dtype=int)
        opp = np.zeros(len(d), dtype=int)
        for side in ("LONG", "SHORT"):
            m = (d.dir == side).to_numpy()
            same[m] = count_before(bi.get(side), a[m], W_VETO)
            opp[m] = count_before(bi.get("SHORT" if side == "LONG" else "LONG"), a[m], W_VETO)
        d["btc_same"], d["btc_opp"] = same, opp
        clu = np.zeros(len(d), dtype=int)
        for (sym, side), arr in ai.items():
            m = ((d.sym != sym) & (d.dir == side)).to_numpy()
            if m.any():
                clu[m] += count_before(arr, a[m], W_CLU)
        d["clu"] = clu
        out[p] = d
    return out


def main() -> None:
    tabs = prep({p: table(p) for p in PROF})

    print("\n1. Связь признаков с шириной стопа (медиана stop_pct по группам)\n")
    for p in PROF:
        d = tabs[p]
        v = d[d.btc_opp > 0], d[d.btc_opp == 0]
        b = pd.qcut(d.clu.rank(method="first"), 4, labels=False)
        print(f"   {p}: вето есть {v[0].stop_pct.median():.2f}% / вето нет "
              f"{v[1].stop_pct.median():.2f}%  |  кластер по квартилям "
              + " ".join(f"{d[b == k].stop_pct.median():.2f}%" for k in range(4))
              + f"  (корр clu↔stop {d.clu.corr(d.stop_pct):+.3f})")

    print("\n2. Эффект вето ВНУТРИ квинтилей ширины стопа (net R: нет вето минус есть)\n")
    print("   профиль" + "".join(f"Q{i+1} стопа".rjust(17) for i in range(5)))
    for p in PROF:
        d = tabs[p]
        b = pd.qcut(d.stop_pct, 5, labels=False, duplicates="drop")
        line = f"   {p:8s}"
        for k in range(5):
            g = d[b == k]
            a_, o_ = g[g.btc_opp == 0], g[g.btc_opp > 0]
            if len(a_) < 100 or len(o_) < 100:
                line += "—".rjust(17)
                continue
            diff = a_.net.mean() - o_.net.mean()
            se = np.sqrt(a_.net.var() / len(a_) + o_.net.var() / len(o_))
            line += f"{diff:+.3f}({diff/se:+.1f})".rjust(17)
        print(line)

    print("\n3. Эффект кластера ВНУТРИ квинтилей стопа (net R: верхний квартиль минус нижний)\n")
    print("   профиль" + "".join(f"Q{i+1} стопа".rjust(17) for i in range(5)))
    for p in PROF:
        d = tabs[p]
        b = pd.qcut(d.stop_pct, 5, labels=False, duplicates="drop")
        line = f"   {p:8s}"
        for k in range(5):
            g = d[b == k]
            if len(g) < 500:
                line += "—".rjust(17)
                continue
            cb = pd.qcut(g.clu.rank(method="first"), 4, labels=False)
            lo, hi = g[cb == 0], g[cb == 3]
            diff = hi.net.mean() - lo.net.mean()
            se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
            line += f"{diff:+.3f}({diff/se:+.1f})".rjust(17)
        print(line)

    print("\n4. Вето по годам и вневыборочно\n")
    for p in PROF:
        d = tabs[p]
        for nm, g in (("вето нет", d[d.btc_opp == 0]), ("вето есть", d[d.btc_opp > 0])):
            years = [(y, g[g.year == y].net.mean()) for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for _, v in years if v > 0)
            ins, oos = g[g.year <= 2023], g[g.year >= 2024]
            print(f"   {p} {nm:10s} n={len(g):6d} net={g.net.mean():+.4f}"
                  f"±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/{len(years)}"
                  f" in={ins.net.mean():+.4f} out={oos.net.mean():+.4f}")
        print()

    print("5. Вето + широкий стоп (совмещение двух рычагов)\n")
    for p in PROF:
        d = tabs[p]
        for th in (1.0, 1.5, 2.5):
            g = d[(d.btc_opp == 0) & (d.stop_pct >= th)]
            if len(g) < 300:
                continue
            years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for v in years if v > 0)
            oos = g[g.year >= 2024]
            print(f"   {p} нет вето и стоп≥{th}%: n={len(g):5d} "
                  f"({len(g)/len(d)*100:4.1f}%) net={g.net.mean():+.4f}"
                  f"±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/{len(years)} "
                  f"out={oos.net.mean():+.4f} (n={len(oos)})")
        print()

    print("6. Сколько сигналов BTC вообще рядом — не вырождено ли вето\n")
    for p in PROF:
        d = tabs[p]
        print(f"   {p}: вето срабатывает у {(d.btc_opp > 0).mean()*100:4.1f}% сделок, "
              f"согласный сигнал BTC у {(d.btc_same > 0).mean()*100:4.1f}%")
    pickle.dump(tabs, open(f"{TPG}/btc_veto.pkl", "wb"))


if __name__ == "__main__":
    main()
