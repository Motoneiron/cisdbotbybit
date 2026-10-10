"""Объясняется ли разница между профилями долей согласованных с трендом сделок?

Четыре независимых наблюдения говорят одно и то же:
  * мой CVD: наклон потока за 12ч, согласованный со сделкой — t=+5.9 по асимметрии;
  * журнал §37: EMA3 на 1H, согласие направления — «по тренду» +0.060R против +0.026R;
  * журнал §34: сделка в сторону дневной свечи лучше на 0.068R, 6 лет из 7;
  * журнал §36: на tf2 контр-трендовых сделок почти НЕТ (7 из 7033), и именно tf2 —
    самый близкий к нулю профиль.

Отсюда гипотеза: рейтинг профилей (tf2 −0.016 > tf8 −0.074 > tf1 −0.082 > tf0 −0.128)
объясняется тем, какая доля их сигналов случайно оказывается по тренду. Если так, то
после условия «по тренду» разница между профилями должна сильно сократиться, а сам
трендовый градиент — держаться на всех четырёх.

Мера тренда как в §37: EMA3 по ЗАКРЫТЫМ 1H-барам, наклон = ema3[i]/ema3[i−1] − 1,
со знаком сделки (>0 = тренд в нашу сторону). Плюс нормировка на ATR, чтобы пороги
были сравнимы между парами.

Запуск: python trend_align_all_tf.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG

PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def trend_1h(sym: str) -> pd.DataFrame:
    """1H-бары пары с наклоном EMA3 и ATR; индекс — момент ДОСТУПНОСТИ бара."""
    from backtest.data import load_ltf
    from backtest.sweep_atr_filter import compute_atr14

    d, _ = load_ltf(tf="1h", since="2019-12-01", until="2026-12-31", symbol=sym)
    d.index = pd.DatetimeIndex(d.index)
    ema3 = d["close"].ewm(span=3, adjust=False).mean()
    out = pd.DataFrame({
        "slope": ema3 / ema3.shift(1) - 1.0,
        "atr_pct": compute_atr14(d) / d["close"],
    })
    # бар с open=t известен только в t+1ч
    out.index = out.index + pd.Timedelta(hours=1)
    return out.dropna()


def attach(tabs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    tr = {}
    for sym in PAIRS:
        try:
            tr[sym] = trend_1h(sym)
        except Exception as e:
            print(f"  {sym}: нет 1H ({e!r})")
    out = {}
    for p, d in tabs.items():
        d = d.copy()
        slope = np.full(len(d), np.nan)
        atrp = np.full(len(d), np.nan)
        for sym, g in d.groupby("sym"):
            t = tr.get(sym)
            if t is None:
                continue
            ti = np.array(t.index, dtype="datetime64[ns]")
            pos = np.searchsorted(ti, np.array(g.anchor, dtype="datetime64[ns]"), "right") - 1
            ok = pos >= 0
            rows = g.index.to_numpy()[ok]
            slope[d.index.get_indexer(rows)] = t["slope"].to_numpy()[pos[ok]]
            atrp[d.index.get_indexer(rows)] = t["atr_pct"].to_numpy()[pos[ok]]
        sgn = np.where(d["dir"].to_numpy() == "LONG", 1.0, -1.0)
        d["slope_side"] = sgn * slope * 100.0                 # в % за час
        d["slope_atr"] = sgn * slope / np.where(atrp > 0, atrp, np.nan)
        out[p] = d
    return out


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_tabs.pkl", "rb"))
    t = attach(tabs)

    print("\n1. Доля сделок ПО тренду и net R по сторонам\n")
    print("   профиль   n     доля по тренду    net по тренду     net против    разница (t)")
    for p in PROF:
        d = t[p][t[p].slope_side.notna()]
        a, b = d[d.slope_side > 0], d[d.slope_side <= 0]
        diff = a.net.mean() - b.net.mean()
        se = np.sqrt(a.net.var() / len(a) + b.net.var() / len(b))
        print(f"   {p:6s} {len(d):6d}      {len(a)/len(d)*100:5.1f}%"
              f"       {a.net.mean():+.4f}        {b.net.mean():+.4f}"
              f"     {diff:+.4f} ({diff/se:+.1f})")

    print("\n2. Квинтили наклона в сторону сделки (net R), нормировка на ATR\n")
    print("   профиль " + "".join(f"Q{i+1}".rjust(12) for i in range(5)))
    for p in PROF:
        d = t[p][t[p].slope_atr.notna()]
        b = pd.qcut(d.slope_atr, 5, labels=False, duplicates="drop")
        line = f"   {p:8s}"
        for k in sorted(pd.unique(b)):
            line += f"{d[b == k].net.mean():+.4f}".rjust(12)
        print(line)

    print("\n3. Схлопывается ли разница между профилями при условии «по тренду»?\n")
    base = {p: t[p].net.mean() for p in PROF}
    print("   профиль    без условия     slope_atr>0    slope_atr>0.5   >0.5 и стоп≥1.5%")
    for p in PROF:
        d = t[p]
        line = f"   {p:8s}  {base[p]:+.4f}"
        for m in (d.slope_atr > 0, d.slope_atr > 0.5,
                  (d.slope_atr > 0.5) & (d.stop_pct >= 1.5)):
            g = d[m]
            line += (f"{g.net.mean():+.4f} ({len(g)})".rjust(18) if len(g) >= 200
                     else "мало".rjust(18))
        print(line)

    print("\n4. Проверка ячейки журнала §36 на всех профилях:")
    print("   SHORT & стоп≥2.5% & наклон в сторону сделки в верхнем квинтиле\n")
    for p in PROF:
        d = t[p]
        thr = d.slope_atr.quantile(0.8)
        g = d[(d.dir == "SHORT") & (d.stop_pct >= 2.5) & (d.slope_atr >= thr)]
        if len(g) < 60:
            print(f"   {p}: мало ({len(g)})")
            continue
        pos = sum(1 for y in sorted(g.year.unique()) if g[g.year == y].net.mean() > 0)
        se = g.net.std() / np.sqrt(len(g))
        print(f"   {p}: n={len(g):4d} net={g.net.mean():+.4f}±{se:.4f} лет={pos}/7 "
              f"SL={g.is_sl.mean():.3f}")

    print("\n5. Монотонность градиента наклона по годам (tf2 и tf8, net R)\n")
    for p in ("tf2", "tf8"):
        d = t[p][t[p].slope_atr.notna()]
        print(f"   {p}:")
        for th in (0.0, 0.5, 1.0, 1.5, 2.0):
            g = d[d.slope_atr >= th]
            if len(g) < 150:
                continue
            years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for v in years if v > 0)
            print(f"     наклон≥{th:.1f} ATR: n={len(g):5d} net={g.net.mean():+.4f}"
                  f"±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/{len(years)}")
    pickle.dump(t, open(f"{TPG}/cross_tf_trend.pkl", "wb"))


if __name__ == "__main__":
    main()
