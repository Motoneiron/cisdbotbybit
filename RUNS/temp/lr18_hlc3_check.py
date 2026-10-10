# -*- coding: utf-8 -*-
"""Чувствительность к версии VWAP: close (research) vs hlc3 (боевой TZ v6).

Гоняет expanding walk-forward base11 с подменённой колонкой vd на hlc3-версию.
Только чтение, пишет lr18_sol_feats_hlc3.pkl (для справки).
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "D:/PYTHON")
sys.path.insert(0, "D:/PYTHON/CISDBOT")
from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
BASE11 = ["sweep_atr", "vol_ratio_scan", "quality_score", "vd", "stoch_k", "macd_hist",
          "ema_distance_atr", "atr_percentile", "prior_touches", "liquidity_distance", "ema_slope_side"]


def vw_hlc3(df):
    typ = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    pv = typ * df["volume"]
    day = df.index.floor("D")
    return pv.groupby(day).cumsum() / df["volume"].groupby(day).cumsum()


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


def run(df, tag):
    df = df.reset_index(drop=True)
    df["y"] = np.where(df.outcome == "tp", 1.0, np.where(df.outcome == "sl", 0.0, np.nan))
    pcol = f"p_{tag}"
    df[pcol] = np.nan
    for ty in range(2021, 2027):
        tr = df[(df.year < ty) & df.y.notna()]
        te_idx = df.index[df.year == ty]
        mu = tr[BASE11].astype(float).mean()
        sd = tr[BASE11].astype(float).std().replace(0, 1.0)
        ztr = ((tr[BASE11].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        zte = ((df.loc[te_idx, BASE11].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        w = fit_lr(np.c_[np.ones(len(tr)), ztr.to_numpy(float)], tr.y.to_numpy(float))
        df.loc[te_idx, pcol] = 1.0 / (1.0 + np.exp(-np.clip(np.c_[np.ones(len(te_idx)), zte.to_numpy(float)] @ w, -30, 30)))
    print(f"--- {tag} ---")
    for ty in range(2021, 2027):
        te = df[df.year == ty]
        d = te[te.outcome.isin(["tp", "sl"])]
        a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
        ntr = int(((df.year < ty) & df.y.notna()).sum())
        print(f"  {ty}: ntr={ntr} AUC={a:.3f}")
    te = df[(df.year >= 2024) & df[pcol].notna()]
    d = te[te.outcome.isin(["tp", "sl"])]
    a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
    lo, hi = te[pcol].quantile([1 / 3, 2 / 3])
    low = te[te[pcol] <= lo]; high = te[te[pcol] >= hi]
    wl = 100 * (low[low.outcome.isin(['tp','sl'])].outcome == 'tp').mean()
    wh = 100 * (high[high.outcome.isin(['tp','sl'])].outcome == 'tp').mean()
    print(f"  свод 2024-26: AUC {a:.3f} | низ WR {wl:.1f}% avg {low.r_net.mean():+.3f} | верх WR {wh:.1f}% avg {high.r_net.mean():+.3f}")
    if "train weights for <2025" :
        tr = df[(df.year < 2025) & df.y.notna()]
        print(f"  n train(2020-2024, для весов <2025) = {len(tr)}")
    return df


def main():
    feats = pd.read_pickle(f"{BASE}/lr18_sol_feats.pkl").reset_index(drop=True)
    # пересчёт vd на hlc3
    vd_h = np.full(len(feats), np.nan)
    for (prof, year), idx in feats.groupby(["prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol="SOL")
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        atr = compute_atr14(dft).to_numpy(float)
        cl = dft["close"].astype(float).to_numpy(float)
        vw = vw_hlc3(dft).to_numpy(float)
        fts = pd.to_datetime(feats.loc[idx, "from_ts"])
        ii = np.searchsorted(ts, (fts - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
        good = (ii >= 30) & (ii < len(dft))
        pos = np.where(good, ii, 0)
        vd_h[idx] = np.where(good & (atr[pos] > 0), (cl[pos] - vw[pos]) / atr[pos], np.nan)
    feats["vd_hlc3"] = vd_h
    feats.to_pickle(f"{BASE}/lr18_sol_feats_hlc3.pkl")

    df_close = feats.copy()
    df_hlc3 = feats.copy()
    df_hlc3["vd"] = df_hlc3["vd_hlc3"]

    rc = run(df_close, "close_vd")
    rh = run(df_hlc3, "hlc3_vd")
    # сравнить колонки vd
    m = rc["vd"].notna() & rh["vd_hlc3"].notna()
    d = (rc.loc[m, "vd"] - rh.loc[m, "vd_hlc3"]).abs()
    print(f"\nvd close vs hlc3: med {d.median():.4f} | max {d.max():.4f} | >1e-3: {100*(d>1e-3).mean():.1f}%")


if __name__ == "__main__":
    main()
