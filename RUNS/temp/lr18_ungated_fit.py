# -*- coding: utf-8 -*-
"""LR-формулы на ГОЛОМ потоке (ungated, SOL): base11 и short3/short4.

Читает lr18_ungated_feats.pkl. Expanding walk-forward (фит — строго прошлые годы).
Выход: lr18_ungated_report.md + lr18_ungated_pred.pkl.
Сравнение с v2-серией: base11 0.560 / short3 0.557 / short4 0.569 (свод 2024-26).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

BASE11 = ["sweep_atr", "vol_ratio_scan", "quality_score", "vd", "stoch_k", "macd_hist",
          "ema_distance_atr", "atr_percentile", "prior_touches", "liquidity_distance", "ema_slope_side"]
SHORT3 = ["t_h", "atr_percentile", "quality_score"]
SHORT4 = SHORT3 + ["liquidity_distance"]

MODELS = {"base11": BASE11, "short3": SHORT3, "short4": SHORT4}


def fit_lr(X, y, lam=1.0, iters=60):
    n, d = X.shape
    w = np.zeros(d)
    for _ in range(iters):
        z = np.clip(X @ w, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        Wd = np.clip(p * (1 - p), 1e-6, None)
        g = X.T @ (p - y) + lam * np.r_[0.0, w[1:]]
        H = X.T @ (X * Wd[:, None]) + lam * np.diag(np.r_[0.0, np.ones(d - 1)])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return w


def auc(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float)
    m = np.isfinite(y) & np.isfinite(s)
    y, s = y[m], s[m]
    npos = y.sum(); nneg = len(y) - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    r = pd.Series(s).rank().to_numpy()
    return float((r[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main():
    df = pd.read_pickle(f"{BASE}/lr18_ungated_feats.pkl").reset_index(drop=True)
    if "vd" not in df.columns:
        df["vd"] = df["vd_conf"]
    rep = []
    w = rep.append
    w("# LR-формулы на ГОЛОМ потоке (ungated SOL, без фильтров и гейта)\n")
    w(f"Поток: {len(df)} сделок 2020–2026, LIMIT, filters-off, min_stop 0.25%, TP1R, комиссии Bybit.")
    w(f"WR(tp/sl)={wr(df):.1f}%, ΣR(нетто)={df.r_net.sum():+.1f}, avg={df.r_net.mean():+.3f}")
    tp = int((df.outcome == 'tp').sum()); sl = int((df.outcome == 'sl').sum()); tm = int((df.outcome == 'time').sum())
    w(f"TP/SL/TIME = {tp}/{sl}/{tm} | по годам: {df.groupby('year').size().to_dict()}\n")

    for tag in ("base11", "short3", "short4"):
        feats = MODELS[tag]
        pcol = f"p_{tag}"
        df[pcol] = np.nan
        rows = []
        for ty in (2021, 2022, 2023, 2024, 2025, 2026):
            tr = df[(df.year < ty) & df.y.notna() & df[feats].notna().all(axis=1)]
            te_idx = df.index[df.year == ty]
            if len(tr) < 50:
                continue
            mu = tr[feats].astype(float).mean()
            sd = tr[feats].astype(float).std().replace(0, 1.0)
            ztr = ((tr[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
            zte = ((df.loc[te_idx, feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
            wgt = fit_lr(np.c_[np.ones(len(tr)), ztr.to_numpy(float)], tr.y.to_numpy(float))
            p = 1.0 / (1.0 + np.exp(-np.clip(np.c_[np.ones(len(te_idx)), zte.to_numpy(float)] @ wgt, -30, 30)))
            df.loc[te_idx, pcol] = p
            te = df.loc[te_idx]
            dd = te[te.outcome.isin(["tp", "sl"])]
            a = auc(dd.y.to_numpy(), df.loc[dd.index, pcol].to_numpy())
            br = float(np.mean((df.loc[dd.index, pcol] - dd.y) ** 2)) if len(dd) else np.nan
            rows.append((ty, len(tr), int(dd.shape[0]), a, br))

        w(f"\n## {tag}\n")
        w("| OOS год | n_train | n_test(tp/sl) | AUC | Brier |")
        w("|---|---|---|---|---|")
        for ty, ntr, nte, a, br in rows:
            w(f"| {ty} | {ntr} | {nte} | {a:.3f} | {br:.3f} |")
        # своды
        for lo, hi, name in ((2021, 2026, "2021–26 (все OOS)"), (2024, 2026, "2024–26 (сравн. с v2)")):
            dd = df[(df.year >= lo) & (df.year <= hi) & df.outcome.isin(["tp", "sl"]) & df[pcol].notna()]
            a = auc(dd.y.to_numpy(), dd[pcol].to_numpy())
            br = float(np.mean((dd[pcol] - dd.y) ** 2))
            w(f"- свод {name}: n={len(dd)} AUC {a:.3f} Brier {br:.3f}")
            # терцили свода
            lo_q, hi_q = dd[pcol].quantile([1 / 3, 2 / 3])
            low = dd[dd[pcol] <= lo_q]; high = dd[dd[pcol] >= hi_q]
            w(f"  - терцили: низ WR={wr(low):.1f}% avgR={low.r_net.mean():+.3f} (n={len(low)}) | "
              f"верх WR={wr(high):.1f}% avgR={high.r_net.mean():+.3f} (n={len(high)})")
        # терцили по годам
        w("  - терцили по годам:")
        for ty in (2024, 2025, 2026):
            dd = df[(df.year == ty) & df.outcome.isin(["tp", "sl"]) & df[pcol].notna()]
            if len(dd) < 30:
                continue
            lo_q, hi_q = dd[pcol].quantile([1 / 3, 2 / 3])
            low = dd[dd[pcol] <= lo_q]; high = dd[dd[pcol] >= hi_q]
            w(f"    {ty}: низ WR={wr(low):.1f}%/**{low.r_net.mean():+.3f}R** (n={len(low)}) | "
              f"верх WR={wr(high):.1f}%/**{high.r_net.mean():+.3f}R** (n={len(high)})")

    # сравнение с v2
    w("\n## Сравнение с v2-серией (SOL, гейт-поток)\n")
    w("| модель | ungated 2024–26 AUC | v2 (2024–26) AUC | ungated все OOS | v2 все |")
    w("|---|---|---|---|---|")
    v2map = {"base11": 0.560, "short3": 0.557, "short4": 0.569}
    for tag in ("base11", "short3", "short4"):
        pcol = f"p_{tag}"
        dd = df[(df.year >= 2024) & (df.year <= 2026) & df.outcome.isin(["tp", "sl"]) & df[pcol].notna()]
        a26 = auc(dd.y.to_numpy(), dd[pcol].to_numpy())
        dd2 = df[(df.year >= 2021) & df.outcome.isin(["tp", "sl"]) & df[pcol].notna()]
        aa = auc(dd2.y.to_numpy(), dd2[pcol].to_numpy())
        w(f"| {tag} | {a26:.3f} | {v2map[tag]:.3f} | {aa:.3f} | — |")

    with open(f"{BASE}/lr18_ungated_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    df.to_pickle(f"{BASE}/lr18_ungated_pred.pkl")
    print("saved lr18_ungated_report.md + lr18_ungated_pred.pkl")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
