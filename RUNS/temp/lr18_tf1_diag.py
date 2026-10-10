# -*- coding: utf-8 -*-
"""Диагностика tf1: одномерные AUC по годам (t_log, atr_pct, sp) для d822/d998. Только чтение."""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/lr18_tf1_feats.pkl")
df["y"] = np.where(df.outcome == "tp", 1.0, np.where(df.outcome == "sl", 0.0, np.nan))


def auc(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float)
    m = np.isfinite(y) & np.isfinite(s)
    y, s = y[m], s[m]
    npos = y.sum(); nneg = len(y) - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    r = pd.Series(s).rank().to_numpy()
    return float((r[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


for src in ("d822", "d998"):
    d = df[df.src == src]
    print(f"### {src}")
    for col in ("t_log", "t_h", "atr_percentile", "sp", "rr", "ph4h", "stoch_k", "macd_hist", "ema_dist_atr", "vd", "vol_ratio"):
        line = f"  {col:16s}"
        for y_ in (2024, 2025, 2026):
            g = d[d.year == y_]
            line += f" | {y_}: {auc(g.y, g[col]):.3f} (n={int(g.y.notna().sum())})"
        print(line)
    print()

# терцили t_log по годам (d998)
for src in ("d822", "d998"):
    d = df[df.src == src]
    print(f"### {src}: терцили t_h по годам (WR / avgR по всем исходам)")
    for y_ in (2024, 2025, 2026):
        g = d[d.year == y_].copy()
        lo, hi = g["t_h"].quantile([1 / 3, 2 / 3])
        low = g[g.t_h <= lo]; high = g[g.t_h >= hi]
        wl = 100 * (low[low.outcome.isin(['tp','sl'])].outcome == 'tp').mean()
        wh = 100 * (high[high.outcome.isin(['tp','sl'])].outcome == 'tp').mean()
        print(f"  {y_}: низ t_h<= {lo/60:.1f}ч: WR {wl:.1f}% avgR {low.r.mean():+.3f} (n={len(low)}) | "
              f"верх >= {hi/60:.1f}ч: WR {wh:.1f}% avgR {high.r.mean():+.3f} (n={len(high)})")
    print()
