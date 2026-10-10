"""agg_live.py — агрегатор pkl-прогонов live-модели (live_final/, live_tf/).

Собирает по конфигу: по годам и суммарно: n, ΣR, avg R, tp/sl/time, сделок/день.
Запуск: python agg_live.py ms1.0_wait30 ms1.0_hold48 ...   (папки в live_final)
        python agg_live.py live_tf/tf8 live_tf/tf1 ...
"""
from __future__ import annotations

import glob
import os
import pickle
import sys

import pandas as pd

ROOT = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
# дней в годах (по факту данных 2024-01-01..2026-09-01)
DAYS = {2024: 366, 2025: 365, 2026: 243}


def load_dir(sub: str):
    files = sorted(glob.glob(os.path.join(ROOT, sub, "*.pkl")))
    rows = []
    for f in files:
        try:
            rows += pickle.load(open(f, "rb"))
        except Exception as e:
            print(f"  !! {f}: {e}")
    return rows


def fix_tp_gross(df):
    """Старые tp-конфиги писали r тейков с gross=1.0. Корректируем, если нашли
    расхождение между реальным gross и r+fee (порог 0.15R)."""
    m = df.outcome == "tp"
    if not m.any():
        return df
    gr = (df.tp - df.entry).abs() / (df.entry - df.stop).abs()
    rr = df.r + 0.00072 / df.sp
    if (gr[m].median() - rr[m].median()) > 0.15:
        add = gr[m] - 1.0
        df.loc[m, "r"] = df.loc[m, "r"] + add
        print(f"  [fix-tp] скорректировано gross: +{add.mean():.3f}R в среднем на {int(m.sum())} tp")
    return df


def agg(rows):
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    df = fix_tp_gross(df)
    df["year"] = pd.to_datetime(df["scan"]).dt.year
    out = {}
    for y, g in df.groupby("year"):
        out[y] = dict(n=len(g), sr=g.r.sum(), avg=g.r.mean(),
                      tp=(g.outcome == "tp").sum(), sl=(g.outcome == "sl").sum(),
                      tm=(g.outcome == "time").sum())
    out["ALL"] = dict(n=len(df), sr=df.r.sum(), avg=df.r.mean(),
                      tp=(df.outcome == "tp").sum(), sl=(df.outcome == "sl").sum(),
                      tm=(df.outcome == "time").sum())
    return out


def main():
    for sub in sys.argv[1:]:
        rows = load_dir(sub)
        a = agg(rows)
        name = sub.rstrip("/")
        if a is None:
            print(f"\n=== {name}: ПУСТО")
            continue
        print(f"\n=== {name}")
        for y in sorted([k for k in a if k != "ALL"]) + (["ALL"] if "ALL" in a else []):
            d = a[y]
            days = DAYS.get(y, 365) if y != "ALL" else sum(DAYS.values())
            per_day = d["n"] / days
            print(f"  {y}: n={d['n']:>4} SR={d['sr']:+7.1f} avg={d['avg']:+.4f} "
                  f"tp/sl/time={d['tp']}/{d['sl']}/{d['tm']} trades/day={per_day:.2f}")


if __name__ == "__main__":
    main()
