"""Биток как ведущий актив: помогает ли совпадение сделки по времени с сигналом BTC.

Мысль пользователя: крипта коррелирует, биток главный, значит сделка на альте рядом по
времени с сигналом на битке в ту же сторону может быть качественнее.

Три проверки, все строго причинные — окно только НАЗАД от якоря решения, потому что в
момент входа известны лишь те сигналы BTC, которые уже случились. (Именно на этом
сгорел «эффект толпы» из прошлого разбора: там считались заполненные сделки, то есть
будущее.)

1. Совпадение с сигналом BTC по времени: есть ли сигнал BTC того же/обратного
   направления в окне [якорь − W, якорь] — по всем профилям BTC сразу.
2. Кластеры вообще: сколько сигналов той же стороны по ВСЕМ парам рядом по времени
   (проверка архивного conc_same на честном якоре).
3. Роль самого битка: отличается ли эффект, если считать не сигналы, а направление
   движения BTC за последние часы (тоже причинно, по закрытым 1H-барам).

Запуск: python btc_leader.py
"""
from __future__ import annotations

import pickle
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG, signal_anchors, table

WINDOWS = (0.5, 2.0, 6.0, 12.0)


def btc_index() -> dict[str, np.ndarray]:
    """Якоря всех сигналов BTC по направлениям, объединённые по четырём профилям."""
    acc: dict[str, list] = defaultdict(list)
    for p in PROF:
        for (sym, side), arr in signal_anchors(p).items():
            if sym == "BTC":
                acc[side].append(arr)
    return {k: np.sort(np.concatenate(v)) for k, v in acc.items()}


def all_index() -> dict[tuple[str, str], np.ndarray]:
    acc: dict[tuple[str, str], list] = defaultdict(list)
    for p in PROF:
        for k, arr in signal_anchors(p).items():
            acc[k].append(arr)
    return {k: np.sort(np.concatenate(v)) for k, v in acc.items()}


def count_before(arr: np.ndarray | None, anchors: np.ndarray, w_h: float) -> np.ndarray:
    if arr is None or len(arr) == 0:
        return np.zeros(len(anchors), dtype=int)
    w = np.timedelta64(int(w_h * 60), "m")
    return (np.searchsorted(arr, anchors, "right")
            - np.searchsorted(arr, anchors - w, "left"))


def cell(g: pd.DataFrame) -> str:
    if len(g) < 100:
        return f"n={len(g):5d}  —"
    se = g.net.std() / np.sqrt(len(g))
    return (f"n={len(g):5d} net={g.net.mean():+.4f}±{se:.4f} "
            f"SL={g.is_sl.mean():.3f} WR={g.is_tp.mean():.3f}")


def part1(tabs: dict[str, pd.DataFrame], bi: dict[str, np.ndarray]) -> None:
    print("\n1. Сигнал BTC рядом по времени (окно назад от якоря)\n")
    for p in PROF:
        d = tabs[p][tabs[p].sym != "BTC"].copy()
        a = np.array(d.anchor, dtype="datetime64[ns]")
        print(f"   {p}: альты n={len(d)}, база net={d.net.mean():+.4f}")
        for w in WINDOWS:
            same = np.zeros(len(d), dtype=int)
            opp = np.zeros(len(d), dtype=int)
            for side in ("LONG", "SHORT"):
                m = (d.dir == side).to_numpy()
                same[m] = count_before(bi.get(side), a[m], w)
                opp[m] = count_before(bi.get("SHORT" if side == "LONG" else "LONG"),
                                      a[m], w)
            d["s"], d["o"] = same, opp
            print(f"     окно {w:4.1f}ч:")
            for lbl, g in (("BTC в ту же сторону", d[(d.s > 0) & (d.o == 0)]),
                           ("BTC в обратную",      d[(d.s == 0) & (d.o > 0)]),
                           ("BTC в обе",           d[(d.s > 0) & (d.o > 0)]),
                           ("BTC молчал",          d[(d.s == 0) & (d.o == 0)])):
                print(f"       {lbl:20s} {cell(g)}")
        print()


def part2(tabs: dict[str, pd.DataFrame], ai: dict[tuple[str, str], np.ndarray]) -> None:
    print("\n2. Кластеры: сколько сигналов той же стороны по всем парам рядом\n")
    for p in PROF:
        d = tabs[p].copy()
        a = np.array(d.anchor, dtype="datetime64[ns]")
        for w in (2.0, 6.0):
            cnt = np.zeros(len(d), dtype=int)
            for (sym, side), arr in ai.items():
                m = ((d.sym != sym) & (d.dir == side)).to_numpy()
                if m.any():
                    cnt[m] += count_before(arr, a[m], w)
            d["c"] = cnt
            qs = d.c.quantile([0.25, 0.5, 0.75]).to_list()
            print(f"   {p} окно {w:.0f}ч (квартили числа сигналов рядом: "
                  f"{qs[0]:.0f}/{qs[1]:.0f}/{qs[2]:.0f}):")
            b = pd.qcut(d.c.rank(method="first"), 4, labels=False)
            for k in range(4):
                g = d[b == k]
                print(f"     Q{k+1} (сигналов {g.c.min():.0f}–{g.c.max():.0f}) {cell(g)}")
        print()


def part3(tabs: dict[str, pd.DataFrame]) -> None:
    from trend_lagged import measure

    print("\n3. Движение самого BTC перед входом (закрытые 1H-бары, причинно)\n")
    m = measure("BTC")
    ti = np.array(m.index, dtype="datetime64[ns]")
    cl, at = m["close"].to_numpy(), m["atr"].to_numpy()
    for p in PROF:
        d = tabs[p][tabs[p].sym != "BTC"].copy()
        a = np.array(d.anchor, dtype="datetime64[ns]")
        print(f"   {p}:")
        for h in (2, 6, 12):
            i1 = np.searchsorted(ti, a, "right") - 1
            i0 = np.searchsorted(ti, a - np.timedelta64(h, "h"), "right") - 1
            ok = (i0 >= 0) & (i1 > i0)
            v = np.full(len(d), np.nan)
            den = at[i1[ok]] * np.sqrt(h)
            v[ok] = np.where(den > 0, (cl[i1[ok]] - cl[i0[ok]]) / den, np.nan)
            sgn = np.where(d["dir"].to_numpy() == "LONG", 1.0, -1.0)
            d["btc"] = sgn * v            # >0 = BTC шёл в сторону нашей сделки
            dd = d[d.btc.notna()]
            b = pd.qcut(dd.btc, 5, labels=False, duplicates="drop")
            vals = [dd[b == k].net.mean() for k in sorted(pd.unique(b))]
            lo, hi = dd[b == b.min()], dd[b == b.max()]
            diff = hi.net.mean() - lo.net.mean()
            se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
            print(f"     BTC за {h:2d}ч, квинтили net: " + " ".join(f"{x:+.4f}" for x in vals)
                  + f"   Q5−Q1={diff:+.4f} (t={diff/se:+.1f})")
        # лучшая сторона отдельно по годам
        d6 = d.copy()
        i1 = np.searchsorted(ti, a, "right") - 1
        i0 = np.searchsorted(ti, a - np.timedelta64(6, "h"), "right") - 1
        ok = (i0 >= 0) & (i1 > i0)
        v = np.full(len(d6), np.nan)
        den = at[i1[ok]] * np.sqrt(6)
        v[ok] = np.where(den > 0, (cl[i1[ok]] - cl[i0[ok]]) / den, np.nan)
        d6["btc"] = np.where(d6["dir"].to_numpy() == "LONG", 1.0, -1.0) * v
        for nm, g in (("BTC в нашу сторону", d6[d6.btc > 0]),
                      ("BTC против", d6[d6.btc <= 0])):
            if len(g) < 200:
                continue
            years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for x in years if x > 0)
            print(f"     {nm:20s} {cell(g)} лет={pos}/{len(years)}")
        print()


def main() -> None:
    tabs = {p: table(p) for p in PROF}
    for p in PROF:
        print(f"{p}: {len(tabs[p])} сделок, net {tabs[p].net.mean():+.4f}", flush=True)
    bi, ai = btc_index(), all_index()
    print(f"\nсигналов BTC: " + ", ".join(f"{k} {len(v)}" for k, v in bi.items()))
    part1(tabs, bi)
    part2(tabs, ai)
    part3(tabs)
    pickle.dump(tabs, open(f"{TPG}/btc_leader_tabs.pkl", "wb"))


if __name__ == "__main__":
    main()
