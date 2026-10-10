"""Финальный крест: фильтр потока × минимальный стоп × способ выхода.

Комиссия в R = комиссия в % / стоп в %. Значит отсечка мелких стопов механически
снижает издержки. Проверяем, вытаскивает ли это край потока (align) в плюс и
насколько результат держится по годам (считаем, сколько лет из семи в плюсе —
одна удачная эпоха не считается краем).

Запуск: python scan_cvd_v2c.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scan_cvd_v2b import EXITS, load, net

MIN_STOPS = (0.0, 1.0, 1.5, 2.0, 2.5, 3.0)
PCTL = (0, 40, 60, 70, 80)


def years_positive(d: pd.DataFrame, col: str) -> tuple[int, int]:
    ys = sorted(d.year.unique())
    pos = sum(1 for y in ys if net(d[d.year == y], col) > 0)
    return pos, len(ys)


if __name__ == "__main__":
    df = load()
    d = df[df["align"].notna()].copy()
    print(f"подвыборка с CVD: {len(d)} из {len(df)} сделок\n")
    print("порог align × min stop%: n | лучший выход | net R | лет в плюсе | asym")
    for p in PCTL:
        thr = np.percentile(d["align"], p)
        for ms in MIN_STOPS:
            g = d[(d["align"] >= thr) & (d["stop_pct"] >= ms)]
            if len(g) < 300:
                continue
            best = max(EXITS, key=lambda c: net(g, c))
            nb = net(g, best)
            pos, tot = years_positive(g, best)
            print(f"  p{p:<2d} ms{ms:<4.1f} n={len(g):5d} {best:8s} net={nb:+.4f} "
                  f"лет={pos}/{tot} asym={g.asym.mean():+.3f} "
                  f"комиссия={g.fee_mix.mean():.4f}")
    # самый выгодный вариант отдельно, с разбивкой по годам
    print("\nлучшая комбинация по net, подробно:")
    best_cfg, best_val = None, -9.0
    for p in PCTL:
        thr = np.percentile(d["align"], p)
        for ms in MIN_STOPS:
            g = d[(d["align"] >= thr) & (d["stop_pct"] >= ms)]
            if len(g) < 800:
                continue
            for c in EXITS:
                v = net(g, c)
                if v > best_val:
                    best_val, best_cfg = v, (p, ms, c, len(g))
    p, ms, c, n = best_cfg
    thr = np.percentile(d["align"], p)
    g = d[(d["align"] >= thr) & (d["stop_pct"] >= ms)]
    print(f"  align>p{p}, стоп>={ms}%, выход {c}: n={n}, net={best_val:+.4f} R")
    for y in sorted(g.year.unique()):
        gy = g[g.year == y]
        print(f"    {int(y)} n={len(gy):4d} net={net(gy,c):+.4f}")
