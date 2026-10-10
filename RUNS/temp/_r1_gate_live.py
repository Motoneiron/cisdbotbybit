"""Гейт «направление цены за последний час перед сигналом» на ЖИВОМ якоре (from_ts).

r1_s = (close[i] / close[i - step] - 1) * sgn, где i — последний ПОЛНОСТЬЮ закрытый бар к from_ts,
step = 60 мин / ТФ. Проверяем оба направления правила:
  WITH   : оставляем сделки, идущие ПО часовому движению (r1_s > 0)
  AGAINST: оставляем сделки ПРОТИВ часового движения (r1_s < 0)
Плюс комбинация с деплойным vwap-гейтом, разбивка по годам и по ТФ.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def line(g, lbl, total=None):
    sh = f" ({100*len(g)/total:4.1f}%)" if total else ""
    return (f"  {lbl:32}: n={len(g):6d} WR={wr(g):5.1f}% ΣR={g.r_net.sum():+8.1f} "
            f"avg={g.r_net.mean():+.3f}{sh}")


def main():
    df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl").copy()
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    df["r1"] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        step = int(60 / tfm)
        dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        cl = dft["close"].to_numpy(float)
        ii = np.searchsorted(ts, (df.loc[idx, "from_ts"] - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
        sgn = np.where(df.loc[idx, "dir"].to_numpy() == "LONG", 1.0, -1.0)
        good = (ii >= step + 30) & (ii < len(dft))
        pos = np.where(good, ii, 0)
        prev = np.where(good, ii - step, 0)
        val = np.where(good, (cl[pos] / cl[prev] - 1.0) * sgn, np.nan)
        df.loc[idx, "r1"] = val
        print(f"  [{sym} {prof} {int(year)}] ok", flush=True)
    df.to_pickle(f"{BASE}/stream_r1_live.pkl")

    t = len(df)
    print(f"\nr1 посчитан на {int(df.r1.notna().sum())}/{t}", flush=True)
    print("\n=== КВИНТИЛИ r1 по направлениям (живой якорь) ===", flush=True)
    for dr in ("LONG", "SHORT"):
        s = df[(df["dir"] == dr) & df.r1.notna()].copy()
        s["q"] = pd.qcut(s.r1.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        print(f"  {dr}: " + "  ".join(f"Q{q}:{wr(x):4.0f}%/{x.r_net.mean():+.3f}" for q, x in s.groupby("q", observed=True)), flush=True)

    print("\n=== ГЕЙТ по знаку r1 (весь поток, живой якорь) ===", flush=True)
    print(line(df, "весь поток", t), flush=True)
    print(line(df[df.r1 > 0], "r1>0 (ПО движению)", t), flush=True)
    print(line(df[df.r1 < 0], "r1<0 (ПРОТИВ движения)", t), flush=True)
    print(line(df[df.r1.isna()], "r1 нет", t), flush=True)

    print("\n=== то же + деплойный vwap-гейт ===", flush=True)
    v = df.vd_conf; S = df["dir"] == "SHORT"; L = df["dir"] == "LONG"
    dep = (S & (v <= 0)) | (L & (v >= 0))
    print(line(df[dep], "ДЕПЛОЙ vwap", t), flush=True)
    print(line(df[dep & (df.r1 > 0)], "ДЕПЛОЙ + r1>0", t), flush=True)
    print(line(df[dep & (df.r1 < 0)], "ДЕПЛОЙ + r1<0", t), flush=True)
    print(line(df[(~dep) & (df.r1 > 0)], "НЕ-ДЕПЛОЙ + r1>0", t), flush=True)

    print("\n=== по годам: r1>0 vs r1<0 (весь поток) ===", flush=True)
    for y, g in df[df.r1.notna()].groupby("year"):
        a = g[g.r1 > 0]; b = g[g.r1 < 0]
        print(f"  {int(y)}: r1>0 WR={wr(a):5.1f}% avg={a.r_net.mean():+.3f} ΣR={a.r_net.sum():+7.1f} | "
              f"r1<0 WR={wr(b):5.1f}% avg={b.r_net.mean():+.3f} ΣR={b.r_net.sum():+7.1f}", flush=True)

    print("\n=== 2024-26: r1>0 vs r1<0 по ТФ ===", flush=True)
    g = df[(df.year >= 2024) & df.r1.notna()]
    for p in ("tf7", "tf8"):
        a = g[(g.prof == p) & (g.r1 > 0)]; b = g[(g.prof == p) & (g.r1 < 0)]
        print(f"  {p}: r1>0 n={len(a)} WR={wr(a):5.1f}% avg={a.r_net.mean():+.3f} | "
              f"r1<0 n={len(b)} WR={wr(b):5.1f}% avg={b.r_net.mean():+.3f}", flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
