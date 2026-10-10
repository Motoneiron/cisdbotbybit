"""Величина рывка ПРОТИВ сделки прямо перед входом — на каком горизонте живёт эффект.

Опыт с лагом показал: на tf8 «трендовый» эффект даёт t=+3.5 при окне, кончающемся у
входа, и затухает до нуля при сдвиге окна на 4 часа назад. Значит работает не тренд за
12 часов, а свежее движение — сам свип и конфирм. Смысл: чем дальше цену увели против
нас прямо перед входом, тем хуже сделка (мы контрим сильный рывок).

Здесь ищем горизонт, где эффект максимален, и проверяем его как правило отбора:
причинно (всё до якоря), с устойчивостью по годам и вневыборочно.

thrust_Nh = (цена против нас за последние N часов) / (ATR(1H) × √N)

Запуск: python thrust_before_entry.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG
from trend_align_all_tf import PAIRS
from trend_lagged import measure

HORIZONS = (1, 2, 3, 6, 12, 24)


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_tabs.pkl", "rb"))
    meas = {s: measure(s) for s in PAIRS}

    out = {}
    for p, d in tabs.items():
        d = d.copy()
        for h in HORIZONS:
            val = np.full(len(d), np.nan)
            for sym, g in d.groupby("sym"):
                m = meas.get(sym)
                if m is None:
                    continue
                ti = np.array(m.index, dtype="datetime64[ns]")
                cl, at = m["close"].to_numpy(), m["atr"].to_numpy()
                a = np.array(g.anchor, dtype="datetime64[ns]")
                i1 = np.searchsorted(ti, a, "right") - 1
                i0 = np.searchsorted(ti, a - np.timedelta64(h, "h"), "right") - 1
                ok = (i0 >= 0) & (i1 > i0)
                v = np.full(len(g), np.nan)
                den = at[i1[ok]] * np.sqrt(h)
                v[ok] = np.where(den > 0, (cl[i1[ok]] - cl[i0[ok]]) / den, np.nan)
                val[d.index.get_indexer(g.index.to_numpy())] = v
            # знак: >0 = цену увели ПРОТИВ нашей сделки
            sgn = np.where(d["dir"].to_numpy() == "LONG", -1.0, 1.0)
            d[f"thrust{h}"] = sgn * val
        out[p] = d

    print("\n1. net R по квинтилям рывка против сделки (Q1 — рывка нет, Q5 — сильный)\n")
    for p in PROF:
        print(f"   {p}:")
        for h in HORIZONS:
            d = out[p][out[p][f"thrust{h}"].notna()]
            b = pd.qcut(d[f"thrust{h}"], 5, labels=False, duplicates="drop")
            vals = [d[b == k].net.mean() for k in sorted(pd.unique(b))]
            lo, hi = d[b == b.min()], d[b == b.max()]
            diff = lo.net.mean() - hi.net.mean()
            se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
            print(f"     {h:2d}ч  " + " ".join(f"{v:+.4f}" for v in vals)
                  + f"   Q1−Q5={diff:+.4f} (t={diff/se:+.1f})")

    print("\n2. Правило «рывок против нас не больше X» на лучшем горизонте (2ч)\n")
    for p in PROF:
        d = out[p]
        for th in (0.5, 0.25, 0.0, -0.25):
            g = d[d.thrust2 <= th]
            if len(g) < 300:
                continue
            years = [(y, g[g.year == y].net.mean()) for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for _, v in years if v > 0)
            print(f"   {p} рывок≤{th:+.2f}: n={len(g):5d} ({len(g)/len(d)*100:4.1f}%) "
                  f"net={g.net.mean():+.4f}±{g.net.std()/np.sqrt(len(g)):.4f} "
                  f"лет={pos}/{len(years)}")
        print()

    print("3. Рывок + широкий стоп, вневыборочно (правило с 2020–2023 → 2024–2026)\n")
    for p in PROF:
        d = out[p]
        for th_t, th_s in ((0.0, 1.5), (0.0, 2.5), (0.25, 1.5)):
            m = (d.thrust2 <= th_t) & (d.stop_pct >= th_s)
            g, ins, oos = d[m], d[m & (d.year <= 2023)], d[m & (d.year >= 2024)]
            if len(ins) < 150 or len(oos) < 150:
                continue
            years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for v in years if v > 0)
            print(f"   {p} рывок≤{th_t} стоп≥{th_s}%: всё n={len(g):5d} "
                  f"net={g.net.mean():+.4f}±{g.net.std()/np.sqrt(len(g)):.4f} "
                  f"лет={pos}/{len(years)} | in={ins.net.mean():+.4f} "
                  f"out={oos.net.mean():+.4f} (n={len(oos)})")
        print()

    print("4. Связь рывка с шириной стопа (не переодетая ли это комиссия)\n")
    for p in PROF:
        d = out[p][out[p].thrust2.notna()]
        b = pd.qcut(d.thrust2, 5, labels=False, duplicates="drop")
        st = [d[b == k].stop_pct.mean() for k in sorted(pd.unique(b))]
        sl = [d[b == k].is_sl.mean() for k in sorted(pd.unique(b))]
        print(f"   {p}: стоп по квинтилям " + " ".join(f"{v:.2f}%" for v in st)
              + " | доля SL " + " ".join(f"{v:.3f}" for v in sl))
    pickle.dump(out, open(f"{TPG}/thrust.pkl", "wb"))


if __name__ == "__main__":
    main()
