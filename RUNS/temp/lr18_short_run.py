# -*- coding: utf-8 -*-
"""Короткая формула (по ревью): t_sw (часы свип→конфирм) + atr_percentile + quality_score (+стоп).

1) сборка dt_sw = confirm_bar_time - trigger_bar_time (мин) из knn18_live_full по (hash,prof);
2) разрез-аналитика dt_sw (бакеты, по профилям и половинам) — проверка переноса гипотезы «<2ч мусор»;
3) expanding walk-forward: base11 / short3 / short4; формы времени (часы / log1p / рубильник ≥2ч);
4) калибровка и терцили для short3.
Выход: lr18_short_report.md + lr18_sol_short.pkl. Только чтение чужих файлов.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

BASE11 = ["sweep_atr", "vol_ratio_scan", "quality_score", "vd", "stoch_k", "macd_hist",
          "ema_distance_atr", "atr_percentile", "prior_touches", "liquidity_distance", "ema_slope_side"]
SHORT3 = ["t_h", "atr_percentile", "quality_score"]
SHORT4 = SHORT3 + ["liquidity_distance"]


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


def run_wf(df, feats, tag, report):
    pcol = f"p_{tag}"
    df[pcol] = np.nan
    rows = []
    for ty in range(2021, 2027):
        tr = df[(df.year < ty) & df.y.notna()]
        te_idx = df.index[df.year == ty]
        mu = tr[feats].astype(float).mean()
        sd = tr[feats].astype(float).std().replace(0, 1.0)
        ztr = ((tr[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        zte = ((df.loc[te_idx, feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
        w = fit_lr(np.c_[np.ones(len(tr)), ztr.to_numpy(float)], tr.y.to_numpy(float))
        df.loc[te_idx, pcol] = 1.0 / (1.0 + np.exp(-np.clip(np.c_[np.ones(len(te_idx)), zte.to_numpy(float)] @ w, -30, 30)))
        te = df[df.year == ty]
        d = te[te.outcome.isin(["tp", "sl"])]
        a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
        br = float(np.mean((df.loc[d.index, pcol] - d.y) ** 2)) if len(d) else np.nan
        rows.append((ty, len(tr), len(te), a, br))
        report.append(f"| {tag} | {ty} | {len(tr)} | {len(te)} | {a:.3f} | {br:.3f} |")
    te = df[(df.year >= 2024) & df[pcol].notna()]
    d = te[te.outcome.isin(["tp", "sl"])]
    a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
    mv = df.loc[df.year >= 2025, pcol]
    return rows, a


def main():
    df = pd.read_pickle(f"{BASE}/lr18_sol_feats.pkl").reset_index(drop=True)
    df["y"] = np.where(df.outcome == "tp", 1.0, np.where(df.outcome == "sl", 0.0, np.nan))

    # --- dt_sw из knn18_live_full по (hash, prof) ---
    src = pd.read_pickle(f"{BASE}/knn18_live_full.pkl")
    kk = lambda d: d["hash"].astype(str) + "|" + d["prof"].astype(str)
    mp_t = dict(zip(kk(src), src["trigger_bar_time"]))
    mp_c = dict(zip(kk(src), src["confirm_bar_time"]))
    df["tbt"] = pd.to_datetime([mp_t.get(x) for x in kk(df)])
    df["cbt"] = pd.to_datetime([mp_c.get(x) for x in kk(df)])
    df["dt_sw_min"] = (df["cbt"] - df["tbt"]).dt.total_seconds() / 60.0
    df["t_h"] = df["dt_sw_min"] / 60.0
    df["t_log"] = np.log1p(df["dt_sw_min"])
    df["t_bin"] = (df["dt_sw_min"] >= 120).astype(float)

    report = []
    w = report.append
    w("# Короткая формула SOL — отчёт\n")
    w(f"n = {len(df)}; NaN tbt/cbt: {int(df.tbt.isna().sum())}; каузальность cbt<=from_ts: "
      f"{100*(df.cbt <= pd.to_datetime(df.from_ts)).mean():.1f}%")
    w("")
    w("## 1. Разрез dt_sw (свип→конфирм) по нашим данным\n")

    for tag, lo, hi in (("0–30м", 0, 30), ("30–60м", 30, 60), ("60–120м", 60, 120),
                        ("120–240м", 120, 240), ("240м+", 240, 10**9)):
        g = df[(df.dt_sw_min >= lo) & (df.dt_sw_min < hi)]
        w(f"- {tag}: n={len(g):4d} | WR={wr(g):5.1f}% | avgR={g.r_net.mean():+.3f}")
    w("")
    for prof in ("tf7", "tf8"):
        for tag, sub in (("ALL", None), ("2020–2023", df.year <= 2023), ("2024–2026", df.year >= 2024)):
            g = df[df.prof == prof]
            if sub is not None:
                g = g[sub]
            a = g[g.dt_sw_min >= 120]; b = g[g.dt_sw_min < 120]
            w(f"- {prof} {tag}: <2ч n={len(b):4d} WR={wr(b):5.1f}% avgR={b.r_net.mean():+.3f} | "
              f">=2ч n={len(a):4d} WR={wr(a):5.1f}% avgR={a.r_net.mean():+.3f}")
    w("")

    w("## 2. Expanding walk-forward\n")
    w("| модель | OOS год | n_train | n_test | AUC | Brier |")
    w("|---|---|---|---|---|---|")
    res = {}
    for tag, feats in (("base11", BASE11), ("short3", SHORT3), ("short4", SHORT4)):
        rows, a24 = run_wf(df, feats, tag, report)
        res[tag] = (rows, a24)

    w("\n## 3. Свод 2024–2026 и терцили\n")
    for tag in ("base11", "short3", "short4"):
        pcol = f"p_{tag}"
        te = df[(df.year >= 2024) & df[pcol].notna()].copy()
        d = te[te.outcome.isin(["tp", "sl"])]
        a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
        lo_, hi_ = te[pcol].quantile([1 / 3, 2 / 3])
        low = te[te[pcol] <= lo_]; high = te[te[pcol] >= hi_]
        w(f"- {tag}: AUC(2024-26)={a:.3f} | низ терциль WR={wr(low):.1f}% avgR={low.r_net.mean():+.3f} | "
          f"верх терциль WR={wr(high):.1f}% avgR={high.r_net.mean():+.3f}")
    w("")
    w("По годам (терцили, short3):")
    for ty in (2024, 2025, 2026):
        te = df[(df.year == ty) & df["p_short3"].notna()].copy()
        lo_, hi_ = te["p_short3"].quantile([1 / 3, 2 / 3])
        low = te[te["p_short3"] <= lo_]; high = te[te["p_short3"] >= hi_]
        w(f"- {ty}: низ WR={wr(low):.1f}% avgR={low.r_net.mean():+.3f} | верх WR={wr(high):.1f}% avgR={high.r_net.mean():+.3f}")

    w("\n## 4. Форма time-фичи (short3, свод 2024–26 AUC)\n")
    for tag, col in (("часы (t_h)", "t_h"), ("log1p(мин)", "t_log"), ("рубильник >=2ч", "t_bin")):
        feats = [col, "atr_percentile", "quality_score"]
        df2 = df.copy()
        rows, a24 = run_wf(df2, feats, f"form_{col}", [])
        w(f"- {tag}: свод AUC 2024–26 = {a24:.3f} | по годам " +
          " ".join(f"{ty}:{a:.3f}" for ty, _, _, a, _ in rows))

    w("\n## 5. Коэффициенты short3 (train < 2025)\n")
    tr = df[(df.year < 2025) & df.y.notna()]
    mu = tr[SHORT3].astype(float).mean(); sd = tr[SHORT3].astype(float).std().replace(0, 1.0)
    ztr = ((tr[SHORT3].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
    Xtr = np.c_[np.ones(len(tr)), ztr.to_numpy(float)]
    wsum = fit_lr(Xtr, tr.y.to_numpy(float))
    for nm, b0, s0 in zip(["const"] + SHORT3, wsum, sd.tolist() + [0]):
        w(f"- {nm}: {b0:+.3f}" + (f" (1σ = {s0:.3f})" if nm != 'const' else ""))

    # сохранить
    keep = ["sym", "prof", "year", "dir", "outcome", "r_net", "from_ts", "hash", "y",
            "dt_sw_min", "t_h", "t_log", "t_bin", "p_base11", "p_short3", "p_short4"] + BASE11
    keep = [c for c in keep if c in df.columns]
    df[keep].to_pickle(f"{BASE}/lr18_sol_short.pkl")
    with open(f"{BASE}/lr18_short_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(report))
    print("saved lr18_short_report.md, lr18_sol_short.pkl")
    print("\n".join(report[:40]))


if __name__ == "__main__":
    main()
