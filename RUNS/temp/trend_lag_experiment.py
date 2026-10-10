"""Чистый опыт: одно окно 12ч, отличается только конец — у входа или за 2ч до него.

Зачем. Вывод «край трендовый, сетап контртрендовый» встречался четыре раза (мой CVD
slope_12h/push_12h, журнал §34 дневная свеча, §36 наклон на tf2, §37 EMA3 1H). Во всех
случаях окно измерения кончалось НА моменте решения, то есть включало сам конфирм-бар —
а конфирм это и есть самое свежее направленное движение сетапа. Тогда «сделка по тренду»
частично означает «конфирм был сильным», и это уже не про тренд.

Опыт: для каждой сделки считаем ход цены за 12 часов дважды — до якоря и до (якорь − 2ч).
Длина окна одинаковая, меняется только конец. Если знак эффекта переворачивается, значит
работал конфирм-бар, а не тренд.

Запуск: python trend_lag_experiment.py
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

WIN_H = 12
LAGS = (0, 1, 2, 4, 8)


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_tabs.pkl", "rb"))
    meas = {s: measure(s) for s in PAIRS}

    out = {}
    for p, d in tabs.items():
        d = d.copy()
        for lag in LAGS:
            val = np.full(len(d), np.nan)
            for sym, g in d.groupby("sym"):
                m = meas.get(sym)
                if m is None:
                    continue
                ti = np.array(m.index, dtype="datetime64[ns]")
                cl, at = m["close"].to_numpy(), m["atr"].to_numpy()
                a = np.array(g.anchor, dtype="datetime64[ns]")
                i1 = np.searchsorted(ti, a - np.timedelta64(lag, "h"), "right") - 1
                i0 = np.searchsorted(ti, a - np.timedelta64(lag + WIN_H, "h"), "right") - 1
                ok = (i0 >= 0) & (i1 > i0)
                v = np.full(len(g), np.nan)
                den = at[i1[ok]] * np.sqrt(WIN_H)
                v[ok] = np.where(den > 0, (cl[i1[ok]] - cl[i0[ok]]) / den, np.nan)
                val[d.index.get_indexer(g.index.to_numpy())] = v
            sgn = np.where(d["dir"].to_numpy() == "LONG", 1.0, -1.0)
            d[f"t{lag}"] = sgn * val
        out[p] = d

    print(f"\nход цены за {WIN_H}ч в сторону сделки, окно кончается за N часов до входа")
    print("значение = net R верхнего квинтиля минус нижнего (в скобках t)\n")
    print("   профиль " + "".join(f"лаг {l}ч".rjust(16) for l in LAGS))
    for p in PROF:
        line = f"   {p:8s}"
        for lag in LAGS:
            d = out[p][out[p][f"t{lag}"].notna()]
            b = pd.qcut(d[f"t{lag}"], 5, labels=False, duplicates="drop")
            lo, hi = d[b == b.min()], d[b == b.max()]
            diff = hi.net.mean() - lo.net.mean()
            se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
            line += f"{diff:+.4f}({diff/se:+.1f})".rjust(16)
        print(line)

    print("\nдоля сделок «по тренду» при разных лагах\n")
    print("   профиль " + "".join(f"лаг {l}ч".rjust(12) for l in LAGS))
    for p in PROF:
        line = f"   {p:8s}"
        for lag in LAGS:
            d = out[p][out[p][f"t{lag}"].notna()]
            line += f"{(d[f't{lag}'] > 0).mean()*100:5.1f}%".rjust(12)
        print(line)

    print("\nсвязь между лагами (корреляция) на tf8:\n")
    d = out["tf8"][[f"t{l}" for l in LAGS]].dropna()
    print(d.corr().round(3).to_string())

    print("\nмой признак push_12h из feat_cvd_v2 против лаговых версий (tf8):")
    try:
        fe = []
        for s in PAIRS:
            fe += pickle.load(open(f"{TPG}/feat_cvd_v2/{s}.pkl", "rb"))
        f2 = pd.DataFrame(fe)[["hash", "push_12h", "of_12h", "slope_12h"]]
        m = out["tf8"].merge(f2, on="hash", how="inner")
        m["align_push"] = -m["push_12h"]          # >0 = цена шла в нашу сторону
        print(f"  сделок с обоими признаками: {len(m)}")
        for c in ("align_push", "t0", "t2", "of_12h", "slope_12h"):
            dd = m[m[c].notna()]
            b = pd.qcut(dd[c], 5, labels=False, duplicates="drop")
            lo, hi = dd[b == b.min()], dd[b == b.max()]
            diff = hi.net.mean() - lo.net.mean()
            se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
            print(f"    {c:12s} n={len(dd):6d} Δnet={diff:+.4f} (t={diff/se:+.1f})")
        print("\n  корреляции:")
        print(m[["align_push", "t0", "t2", "of_12h", "slope_12h"]].corr().round(3).to_string())
    except FileNotFoundError:
        print("  фичи CVD v2 не найдены")
    pickle.dump(out, open(f"{TPG}/trend_lag_experiment.pkl", "wb"))


if __name__ == "__main__":
    main()
