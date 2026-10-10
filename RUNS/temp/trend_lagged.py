"""Трендовое согласие, измеренное БЕЗ тавтологии: окно кончается за 2 часа до входа.

Прямая мера (EMA3 на 1H в момент якоря) непригодна для сравнения профилей: конфирм-бар
tf2 — это и есть последний закрытый 1H-бар, а EMA3 со span=3 им и определяется. Отсюда
99,9% «по тренду» у tf2 против 23,1% у tf0 — артефакт соотношения окна и ТФ профиля,
а не рыночная структура (то есть наблюдение журнала §36 «у tf2 контр-трендовых почти нет»
именно про это).

Здесь тренд считается по закрытым 1H-барам в окне [якорь − 26ч, якорь − 2ч]: последние
два часа выброшены, поэтому ни конфирм-бар, ни сам свип в измерение не попадают ни на
одном профиле. Нормировка на ATR(1H), знак — в сторону сделки.

Запуск: python trend_lagged.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG
from trend_align_all_tf import PAIRS

SKIP_H, WIN_H = 2, 24


def measure(sym: str) -> pd.DataFrame:
    from backtest.data import load_ltf
    from backtest.sweep_atr_filter import compute_atr14

    d, _ = load_ltf(tf="1h", since="2019-12-01", until="2026-12-31", symbol=sym)
    d.index = pd.DatetimeIndex(d.index)
    atr = compute_atr14(d)
    out = pd.DataFrame({"close": d["close"], "atr": atr}).dropna()
    out.index = out.index + pd.Timedelta(hours=1)      # момент доступности бара
    return out


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_tabs.pkl", "rb"))
    meas = {}
    for s in PAIRS:
        try:
            meas[s] = measure(s)
        except Exception as e:
            print(f"  {s}: нет данных ({e!r})")

    out = {}
    for p, d in tabs.items():
        d = d.copy()
        val = np.full(len(d), np.nan)
        for sym, g in d.groupby("sym"):
            m = meas.get(sym)
            if m is None:
                continue
            ti = np.array(m.index, dtype="datetime64[ns]")
            cl, at = m["close"].to_numpy(), m["atr"].to_numpy()
            a = np.array(g.anchor, dtype="datetime64[ns]")
            i1 = np.searchsorted(ti, a - np.timedelta64(SKIP_H, "h"), "right") - 1
            i0 = np.searchsorted(ti, a - np.timedelta64(SKIP_H + WIN_H, "h"), "right") - 1
            ok = (i0 >= 0) & (i1 > i0)
            v = np.full(len(g), np.nan)
            denom = at[i1[ok]] * np.sqrt(WIN_H)
            v[ok] = np.where(denom > 0, (cl[i1[ok]] - cl[i0[ok]]) / denom, np.nan)
            val[d.index.get_indexer(g.index.to_numpy())] = v
        sgn = np.where(d["dir"].to_numpy() == "LONG", 1.0, -1.0)
        d["trend"] = sgn * val
        out[p] = d

    print(f"\nтренд за {WIN_H}ч, окно кончается за {SKIP_H}ч до входа, знак в сторону сделки\n")
    print("1. Доля по тренду и net R по сторонам\n")
    print("   профиль   n     доля по тренду   net по тренду    net против   разница (t)")
    for p in PROF:
        d = out[p][out[p].trend.notna()]
        a, b = d[d.trend > 0], d[d.trend <= 0]
        diff = a.net.mean() - b.net.mean()
        se = np.sqrt(a.net.var() / len(a) + b.net.var() / len(b))
        print(f"   {p:6s} {len(d):6d}      {len(a)/len(d)*100:5.1f}%"
              f"      {a.net.mean():+.4f}       {b.net.mean():+.4f}"
              f"    {diff:+.4f} ({diff/se:+.1f})")

    print("\n2. Квинтили тренда (net R)\n")
    print("   профиль " + "".join(f"Q{i+1}".rjust(12) for i in range(5)) + "    Δ(Q5−Q1) t")
    for p in PROF:
        d = out[p][out[p].trend.notna()]
        b = pd.qcut(d.trend, 5, labels=False, duplicates="drop")
        line = f"   {p:8s}"
        for k in sorted(pd.unique(b)):
            line += f"{d[b == k].net.mean():+.4f}".rjust(12)
        lo, hi = d[b == b.min()], d[b == b.max()]
        diff = hi.net.mean() - lo.net.mean()
        se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
        print(line + f"    {diff:+.4f} ({diff/se:+.1f})")

    print("\n3. Тренд + широкий стоп (net R, лет в плюсе)\n")
    for p in PROF:
        d = out[p]
        for th_t, th_s in ((0.0, 1.5), (0.3, 1.5), (0.3, 2.5), (0.6, 2.5)):
            g = d[(d.trend >= th_t) & (d.stop_pct >= th_s)]
            if len(g) < 200:
                continue
            pos = sum(1 for y in sorted(g.year.unique())
                      if len(g[g.year == y]) >= 30 and g[g.year == y].net.mean() > 0)
            tot = sum(1 for y in sorted(g.year.unique()) if len(g[g.year == y]) >= 30)
            print(f"   {p} тренд≥{th_t} стоп≥{th_s}%: n={len(g):5d} "
                  f"net={g.net.mean():+.4f}±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/{tot}")
        print()

    print("4. Вневыборочно (правило на 2020–2023 → проверка 2024–2026)\n")
    for p in PROF:
        d = out[p]
        m = (d.trend >= 0.3) & (d.stop_pct >= 1.5)
        ins, oos = d[m & (d.year <= 2023)], d[m & (d.year >= 2024)]
        if len(ins) < 150 or len(oos) < 150:
            continue
        print(f"   {p}: in={ins.net.mean():+.4f} (n={len(ins)}) "
              f"out={oos.net.mean():+.4f} (n={len(oos)})")
    pickle.dump(out, open(f"{TPG}/cross_tf_trend_lagged.pkl", "wb"))


if __name__ == "__main__":
    main()
