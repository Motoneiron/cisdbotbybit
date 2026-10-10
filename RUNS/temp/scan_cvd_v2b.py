"""Композит «согласованность с потоком» и его экономика.

Скрин v2 показал: край даёт не дивергенция, а совпадение сделки с направлением
потока и цены за 12 часов (slope_12h t=+5.9, push_12h t=−5.1 с обратным знаком).
Дивергенция (цена ушла против нас, поток за нас) работает в минус ⇒ контртренд
на этом таймфрейме не окупается.

Здесь: композит align = z(slope_12h) − z(push_12h), его дециль, чистый R по всем
вариантам выхода, устойчивость по годам и по парам.

Запуск: python scan_cvd_v2b.py
"""
from __future__ import annotations

import glob
import pickle

import numpy as np
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
EXITS = ["r_1.0", "r_1.25", "r_1.5", "r_2.0", "r_3.0", "be0.5_r", "be1.0_r", "tr0.5_r", "tr1.0_r"]


def z(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / s.std()


def load() -> pd.DataFrame:
    tr = []
    for sym in PAIRS:
        for f in glob.glob(f"{BASE}/tp_grid/{sym}_*.pkl"):
            tr += [r for r in pickle.load(open(f, "rb")) if r.get("hold") == 6]
    t = pd.DataFrame(tr)
    fe = []
    for sym in PAIRS:
        try:
            fe += pickle.load(open(f"{BASE}/feat_cvd_v2/{sym}.pkl", "rb"))
        except FileNotFoundError:
            pass
    f2 = pd.DataFrame(fe).drop(columns=["sym", "year"], errors="ignore")
    df = t.merge(f2, on="hash", how="left")
    df["asym"] = df["mfe_r"] - df["mae_r"]
    df["align"] = z(df["slope_12h"]) - z(df["push_12h"])
    df["align_of"] = z(df["of_12h"]) - z(df["push_12h"])
    return df


def net(d: pd.DataFrame, exit_col: str, fee: str = "fee_mix") -> float:
    return float((d[exit_col] - d[fee]).mean())


def deciles(df: pd.DataFrame, col: str, q: int = 10) -> None:
    d = df[df[col].notna()].copy()
    d["b"] = pd.qcut(d[col], q, labels=False, duplicates="drop")
    print(f"\n{col}: дециль | n | asym | net TP1R (mix) | net (maker2) | WR")
    for k in sorted(d.b.unique()):
        g = d[d.b == k]
        wr = float((g["out_1.0"] == "tp").mean())
        print(f"  {k:2d} n={len(g):5d} asym={g.asym.mean():+.3f} "
              f"net={net(g,'r_1.0'):+.4f} maker2={net(g,'r_1.0','fee_maker2'):+.4f} WR={wr:.3f}")


def cuts(df: pd.DataFrame, col: str) -> None:
    d = df[df[col].notna()]
    print(f"\n{col}: порог | доля сделок | asym | лучший выход и его net")
    for p in (0, 20, 40, 50, 60, 70, 80, 90):
        thr = np.percentile(d[col], p)
        g = d[d[col] >= thr]
        best = max(EXITS, key=lambda c: net(g, c))
        print(f"  >p{p:<2d} n={len(g):5d} ({len(g)/len(df)*100:4.1f}% базы) "
              f"asym={g.asym.mean():+.3f} {best}={net(g,best):+.4f} "
              f"r_1.0={net(g,'r_1.0'):+.4f}")


def yearly(df: pd.DataFrame, col: str, p: int) -> None:
    d = df[df[col].notna()]
    thr = np.percentile(d[col], p)
    g = d[d[col] >= thr]
    print(f"\n{col} >p{p}: по годам (n / net r_1.0 / net tr0.5)")
    for y in sorted(g.year.unique()):
        gy = g[g.year == y]
        print(f"  {int(y)} n={len(gy):4d} r_1.0={net(gy,'r_1.0'):+.4f} "
              f"tr0.5={net(gy,'tr0.5_r'):+.4f} asym={gy.asym.mean():+.3f}")
    print(f"  по парам:")
    for s in sorted(g.sym.unique()):
        gs = g[g.sym == s]
        print(f"    {s:5s} n={len(gs):4d} r_1.0={net(gs,'r_1.0'):+.4f} asym={gs.asym.mean():+.3f}")


if __name__ == "__main__":
    df = load()
    print(f"база: {len(df)} сделок, asym {df.asym.mean():+.3f}, "
          f"net TP1R {net(df,'r_1.0'):+.4f} R, комиссия mix {df.fee_mix.mean():.4f}")
    for c in ("slope_12h", "align", "align_of"):
        deciles(df, c)
    for c in ("slope_12h", "align"):
        cuts(df, c)
    yearly(df, "align", 60)
