"""Скрин CVD v2: какая фича реально делит сделки по асимметрии хода.

Метрика отбора — asym = mfe_r − mae_r (насколько дальше цена уходит в нашу сторону,
чем против). Она не зависит от того, где стоит TP, поэтому по ней видно наличие
самого края, а не удачную подгонку выхода. Рядом печатаем чистый R по TP1R с
комиссией, чтобы сразу видеть, хватает ли края на издержки.

Дивергенция собирается здесь: div = z(push) + z(of) — цену увели против нас
(push большой), а поток при этом в нашу сторону (of > 0).

Запуск: python scan_cvd_v2.py
"""
from __future__ import annotations

import glob
import pickle

import numpy as np
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
FEE = "fee_mix"


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
    df["net"] = df["r_1.0"] - df[FEE]
    for w in ("4h", "12h"):
        p, o = df[f"push_{w}"], df[f"of_{w}"]
        df[f"div_{w}"] = (
            (p - p.mean()) / p.std() + (o - o.mean()) / o.std()
        )
    return df


def stats(s: pd.Series) -> tuple[float, float]:
    s = s.dropna()
    if len(s) < 30:
        return np.nan, np.nan
    return float(s.mean()), float(s.mean() / (s.std() / np.sqrt(len(s))))


def screen(df: pd.DataFrame, col: str, q: int = 5) -> None:
    d = df[df[col].notna()]
    if len(d) < 300:
        print(f"{col:16s} мало данных ({len(d)})")
        return
    try:
        b = pd.qcut(d[col], q, labels=False, duplicates="drop")
    except ValueError:
        print(f"{col:16s} не делится")
        return
    parts = []
    for k in sorted(b.unique()):
        g = d[b == k]
        a, ta = stats(g["asym"])
        n_, tn = stats(g["net"])
        parts.append(f"{a:+.3f}({ta:+.1f})/{n_:+.3f}")
    lo, hi = d[b == b.min()], d[b == b.max()]
    diff = hi["asym"].mean() - lo["asym"].mean()
    sd = np.sqrt(hi["asym"].var() / len(hi) + lo["asym"].var() / len(lo))
    print(f"{col:16s} n={len(d):5d} размах={diff:+.3f} t={diff/sd:+.1f} | " + " ".join(parts))


if __name__ == "__main__":
    df = load()
    print(f"сделок {len(df)}, asym сред {df.asym.mean():+.3f}, "
          f"net TP1R {df.net.mean():+.4f} R\n")
    print("квинтили: asym(t)/net — от низкого значения фичи к высокому\n")
    cols = [
        "of_30m", "of_1h", "of_4h", "of_12h",
        "push_1h", "push_4h", "push_12h",
        "accel_4h", "accel_12h", "slope_4h", "slope_12h",
        "sw_of", "sw_of_last10", "sw_vol_z", "sw_range_atr", "sw_absorb",
        "post_of", "post_min",
        "div_4h", "div_12h",
    ]
    for c in cols:
        screen(df, c)
