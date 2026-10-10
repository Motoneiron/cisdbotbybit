# -*- coding: utf-8 -*-
"""LR на tf1: expanding walk-forward для датасетов d822 (до фильтра) и d998 (рабочий, >=2ч).

Читает lr18_tf1_feats.pkl. Выход: lr18_tf1_report.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

MODELS = {
    "m_time": ["t_log"],
    "m_core": ["t_log", "atr_percentile"],
    "m3": ["t_log", "atr_percentile", "sp"],
    "m5": ["t_log", "atr_percentile", "sp", "rr", "ph4h"],
    "m_all": ["t_log", "atr_percentile", "stoch_k", "macd_hist", "ema_dist_atr", "vd",
              "vol_ratio", "sp", "rr", "ph4h"],
}


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
    a = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (a.outcome == "tp").mean() if len(a) else float("nan")


def run(df, src, feats, tag, years, report):
    d = df[df.src == src].copy().reset_index(drop=True)
    d["y"] = np.where(d.outcome == "tp", 1.0, np.where(d.outcome == "sl", 0.0, np.nan))
    pcol = f"p_{tag}"
    d[pcol] = np.nan
    rows = []
    for ty in years:
        tr = d[(d.year < ty) & d.y.notna() & d[feats].notna().all(axis=1)]
        te_idx = d.index[d.year == ty]
        mu = tr[feats].astype(float).mean()
        sd = tr[feats].astype(float).std().replace(0, 1.0)
        ztr = ((tr[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        zte = ((d.loc[te_idx, feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        w = fit_lr(np.c_[np.ones(len(tr)), ztr.to_numpy(float)], tr.y.to_numpy(float))
        p = 1.0 / (1.0 + np.exp(-np.clip(np.c_[np.ones(len(te_idx)), zte.to_numpy(float)] @ w, -30, 30)))
        d.loc[te_idx, pcol] = p
        te = d[d.year == ty]
        dd = te[te.outcome.isin(["tp", "sl"])]
        a = auc(dd.y.to_numpy(), d.loc[dd.index, pcol].to_numpy())
        br = float(np.mean((d.loc[dd.index, pcol] - dd.y) ** 2)) if len(dd) else np.nan
        rows.append((ty, len(tr), int(dd.shape[0]), a, br))
        report.append(f"| {src}/{tag} | {ty} | {len(tr)} | {dd.shape[0]} | {a:.3f} | {br:.3f} |")
    return d, rows


def main():
    df = pd.read_pickle(f"{BASE}/lr18_tf1_feats.pkl").reset_index(drop=True)
    report = []
    w = report.append
    w("# LR-формула на tf1 (15m→4H) — отчёт\n")
    w(f"Всего строк: {len(df)} (d822: {(df.src=='d822').sum()}, d998: {(df.src=='d998').sum()})")
    for src in ("d822", "d998"):
        d = df[df.src == src]
        print(src, "NaN по фичам:", {c: int(d[c].isna().sum()) for c in MODELS["m_all"]}, flush=True)
    w("")

    test_years = {"d822": (2025, 2026), "d998": (2025, 2026)}
    all_res = {}
    w("## 1. Expanding walk-forward (фит — только прошлые годы)\n")
    w("| датасет/модель | OOS год | n_train | n_test | AUC | Brier |")
    w("|---|---|---|---|---|---|")
    for src in ("d822", "d998"):
        for tag, feats in MODELS.items():
            d, rows = run(df, src, feats, tag, test_years[src], report)
            all_res[(src, tag)] = (d, rows)

    w("\n## 2. Терцили и формы времени (на тестовых годах)\n")
    for src in ("d822", "d998"):
        d, _ = all_res[(src, "m_core")]
        te = d[(d.year >= 2025) & d["p_m_core"].notna()].copy()
        lo, hi = te["p_m_core"].quantile([1 / 3, 2 / 3])
        low = te[te["p_m_core"] <= lo]; high = te[te["p_m_core"] >= hi]
        w(f"- {src} m_core 2025–26: низ WR={wr(low):.1f}% avgR={low.r.mean():+.3f} (n={len(low)}) | "
          f"верх WR={wr(high):.1f}% avgR={high.r.mean():+.3f} (n={len(high)})")
    w("")
    # формы времени (comparison)
    for src in ("d822", "d998"):
        d0 = df[df.src == src].copy()
        d0["t_bin"] = (d0["dt_sw_calc"] >= 120).astype(float)
        d0["y"] = np.where(d0.outcome == "tp", 1.0, np.where(d0.outcome == "sl", 0.0, np.nan))
        line = [f"- {src} m_core формы:"]
        for col, name in (("t_log", "log"), ("t_h", "часы"), ("t_bin", ">=2ч бин")):
            for ty in test_years[src]:
                tr = d0[(d0.year < ty) & d0.y.notna()]
                te = d0[(d0.year == ty)]
                feats = [col, "atr_percentile"]
                mu = tr[feats].astype(float).mean(); sd = tr[feats].astype(float).std().replace(0, 1.0)
                ztr = ((tr[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
                zte = ((te[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
                wgt = fit_lr(np.c_[np.ones(len(tr)), ztr.to_numpy(float)], tr.y.to_numpy(float))
                p = 1.0 / (1.0 + np.exp(-np.clip(np.c_[np.ones(len(te)), zte.to_numpy(float)] @ wgt, -30, 30)))
                dd = te[te.outcome.isin(["tp", "sl"])]
                a = auc(dd.y.to_numpy(), pd.Series(p, index=te.index).reindex(dd.index).to_numpy())
                line.append(f"{name} {ty}: AUC {a:.3f} |")
        w(" ".join(line))

    w("\n## 3. Коэффициенты m_core и m5 (d998, fit 2024–25)\n")
    d = df[df.src == "d998"].copy().reset_index(drop=True)
    d["y"] = np.where(d.outcome == "tp", 1.0, np.where(d.outcome == "sl", 0.0, np.nan))
    for tag in ("m_core", "m5"):
        feats = MODELS[tag]
        tr = d[(d.year < 2026) & d.y.notna() & d[feats].notna().all(axis=1)]
        mu = tr[feats].astype(float).mean(); sd = tr[feats].astype(float).std().replace(0, 1.0)
        ztr = ((tr[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        wgt = fit_lr(np.c_[np.ones(len(tr)), ztr.to_numpy(float)], tr.y.to_numpy(float))
        w(f"- **{tag}** (n={len(tr)}): const {wgt[0]:+.3f}")
        for nm, wi in zip(feats, wgt[1:]):
            w(f"  - {nm}: {wi:+.3f} (1σ={sd[nm]:.3f}, среднее {mu[nm]:.3f})")

    with open(f"{BASE}/lr18_tf1_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(report))
    print("saved lr18_tf1_report.md")
    print("\n".join(report[:60]))


if __name__ == "__main__":
    main()
