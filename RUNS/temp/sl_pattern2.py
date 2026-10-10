"""Что даёт единственный устойчивый признак стоповых сделок — узкий стоп.

На живых 32 сделках ни один геометрический признак не выделяется за пределами шума,
а на честной базе (15 382) работает только ширина стопа: доля SL падает с 42% до
17% от узкого квинтиля к широкому. Здесь считаем, что даёт отсечка по стопу как
правило отбора, и держится ли она по годам и на живом периоде.

Запуск: python sl_pattern2.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sl_pattern import base_table, live_table

THRESH = (0.0, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0)


def main() -> None:
    df = base_table()
    print("квинтили ширины стопа (честная база):")
    qs = np.percentile(df.stop_pct, [20, 40, 60, 80])
    print("  границы, %: " + ", ".join(f"{v:.2f}" for v in qs))

    print("\nотсечка по стопу: сколько остаётся, доля SL, net R, лет в плюсе")
    for th in THRESH:
        g = df[df.stop_pct >= th]
        if len(g) < 300:
            continue
        pos = sum(1 for y in sorted(g.year.unique()) if g[g.year == y].net.mean() > 0)
        tot = g.year.nunique()
        se = g.net.std() / np.sqrt(len(g))
        print(f"  >={th:.1f}%  n={len(g):5d} ({len(g)/len(df)*100:4.1f}%) "
              f"SL={g.is_sl.mean():.3f} net={g.net.mean():+.4f}±{se:.4f} "
              f"лет={pos}/{tot} комиссия={g.fee_mix.mean():.4f}")

    print("\nстоп × ширина базы (start_range_atr), net R:")
    df["sq"] = pd.qcut(df.stop_pct, 4, labels=False)
    df["bq"] = pd.qcut(df.start_range_atr, 4, labels=False)
    piv = df.pivot_table(index="sq", columns="bq", values="net", aggfunc="mean")
    cnt = df.pivot_table(index="sq", columns="bq", values="net", aggfunc="size")
    print("  (строки — квартиль стопа, столбцы — квартиль ширины базы)")
    print(piv.round(3).to_string())
    print("  n:")
    print(cnt.to_string())

    print("\nисключение confirm_on_sweep (конфирм-бар и есть бар свипа):")
    for th in (0.0, 1.0, 1.5):
        g = df[df.stop_pct >= th]
        a = g[~g.confirm_on_sweep.astype(bool)]
        print(f"  стоп>={th:.1f}%: всё n={len(g):5d} net={g.net.mean():+.4f} | "
              f"без confirm_on_sweep n={len(a):5d} net={a.net.mean():+.4f}")

    lv = live_table()
    print("\nживой период под то же правило (32 закрытых):")
    for th in (0.0, 1.0, 1.2, 1.5):
        g = lv[lv.stop_pct >= th]
        if not len(g):
            continue
        n_sl = int((g.outcome == "sl").sum())
        n_tp = int((g.outcome == "tp").sum())
        print(f"  стоп>={th:.1f}%: n={len(g):2d} TP={n_tp} SL={n_sl} "
              f"TIME={int((g.outcome=='time').sum())} "
              f"итог={g.pnl_net.sum():+.2f} USDT")
    print("\n  распределение стопа у живых по исходу:")
    for k, v in lv.groupby("outcome"):
        print(f"    {k:5s} n={len(v):2d} медиана стопа {v.stop_pct.median():.2f}% "
              f"мин {v.stop_pct.min():.2f}% макс {v.stop_pct.max():.2f}%")


if __name__ == "__main__":
    main()
