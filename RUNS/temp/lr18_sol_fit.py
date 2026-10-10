# -*- coding: utf-8 -*-
"""LR-формула SOL: walk-forward обучение и оценка. Только чтение lr18_sol_feats.pkl,
пишет lr18_sol_pred.pkl + lr18_sol_report.md.

Схема:
  expanding walk-forward: для каждого года T (2021..2026) модель учится на всех
  годах < T (только matured tp/sl), предсказывает на T. Главный фокус — 2024/2025/2026.
  Признаки стандартизуются по train (clip +-6). IRLS (Ньютон) с L2, как _q_meta_lr.py.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

BASE11 = ["sweep_atr", "vol_ratio_scan", "quality_score", "vd", "stoch_k", "macd_hist",
          "ema_distance_atr", "atr_percentile", "prior_touches", "liquidity_distance", "ema_slope_side"]
# отбор добавок по train-одномерке (см. таблицу кандидатов): rr_planned .535, q_no_conf_fvg .554,
# q_no_start_fvg .551, of1_conf .523 (покрытие 83%), slope_h1 (EMA3-1H наклон, каузальный)
EXT5 = ["rr_planned", "q_no_conf_fvg", "q_no_start_fvg", "of1_conf", "slope_h1"]
EXT16 = BASE11 + EXT5

CANDS = ["rr_planned", "psl_probability", "psl_quartile", "soft_dow", "late_retest", "one_bar_sweep_cisd",
         "confirm_on_sweep", "fib_stretch_market", "q_start_n", "q_never", "q_unreclaim",
         "q_no_start_fvg", "q_no_conf_fvg", "bars_since_pivot", "sp", "sweep_atr", "prior_touches",
         "slope_h1", "r1h", "of1_conf"]


def fit_lr(X: np.ndarray, y: np.ndarray, lam: float = 1.0, iters: int = 60):
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
    z = np.clip(X @ w, -30, 30)
    p = 1.0 / (1.0 + np.exp(-z))
    Wd = np.clip(p * (1 - p), 1e-6, None)
    H = X.T @ (X * Wd[:, None]) + lam * np.diag(np.r_[0.0, np.ones(d - 1)])
    cov = np.linalg.inv(H)
    se = np.sqrt(np.diag(cov))
    return w, se


def auc(y: np.ndarray, s: np.ndarray) -> float:
    y = np.asarray(y, float)
    s = np.asarray(s, float)
    m = np.isfinite(y) & np.isfinite(s)
    y, s = y[m], s[m]
    n_pos = y.sum()
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    r = pd.Series(s).rank().to_numpy()
    return float((r[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def wr(g: pd.DataFrame) -> float:
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def zfit(df, feats, ty, lam=1.0):
    tr = df[(df.year < ty) & df.y.notna()]
    te_idx = df.index[df.year == ty]
    mu = tr[feats].astype(float).mean()
    sd = tr[feats].astype(float).std().replace(0, 1.0)
    ztr = ((tr[feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
    zte = ((df.loc[te_idx, feats].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
    Xtr = np.c_[np.ones(len(tr)), ztr.to_numpy(float)]
    Xte = np.c_[np.ones(len(te_idx)), zte.to_numpy(float)]
    w, se = fit_lr(Xtr, tr.y.to_numpy(float), lam=lam)
    p = 1.0 / (1.0 + np.exp(-np.clip(Xte @ w, -30, 30)))
    return w, se, pd.Series(p, index=te_idx)


def main():
    df = pd.read_pickle(f"{BASE}/lr18_sol_feats.pkl").reset_index(drop=True)
    df["y"] = np.where(df.outcome == "tp", 1.0, np.where(df.outcome == "sl", 0.0, np.nan))

    # --- маппинг slope_1h/r1h из stream_ema3_r1 (для диагностики кандидатов) ---
    try:
        ema = pd.read_pickle(f"{BASE}/stream_ema3_r1.pkl")[["hash", "prof", "slope_h1", "r1h"]]
        kk = lambda d: d["hash"].astype(str) + "|" + d["prof"].astype(str)
        for col in ["slope_h1", "r1h"]:
            mp = dict(zip(kk(ema), ema[col]))
            df[col] = [mp.get(x) for x in kk(df)]
            print(f"{col}: покрытие {df[col].notna().mean():.3f}")
    except Exception as e:
        print("ema3_r1 mapping failed:", e)
    try:
        oi = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")[["hash", "prof", "of1_conf"]]
        kk = lambda d: d["hash"].astype(str) + "|" + d["prof"].astype(str)
        mp = dict(zip(kk(oi), oi["of1_conf"]))
        df["of1_conf"] = [mp.get(x) for x in kk(df)]
        print(f"of1_conf: покрытие {df['of1_conf'].notna().mean():.3f}")
    except Exception as e:
        print("reanchor mapping failed:", e)

    report = []
    wlog = report.append

    wlog(f"# LR-формула SOL — отчёт\n")
    wlog(f"Сделок: {len(df)}; из них tp/sl: {int(df.y.notna().sum())}; time: {int((df.outcome=='time').sum())}")
    wlog(f"Годы: {df.groupby('year').size().to_dict()}\n")

    # ===== expanding walk-forward по всем годам, две модели =====
    folds = [ty for ty in range(2021, 2027)]
    results = {}
    for name, feats in (("base11", BASE11), ("ext16", EXT16)):
        pcol = f"p_{name}"
        df[pcol] = np.nan
        rows = []
        for ty in folds:
            tr = df[(df.year < ty) & df.y.notna()]
            w, se, p = zfit(df, feats, ty)
            df.loc[p.index, pcol] = p.to_numpy()
            te = df[df.year == ty]
            d = te[te.outcome.isin(["tp", "sl"])]
            a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
            brier = float(np.mean((df.loc[d.index, pcol] - d.y) ** 2)) if len(d) else np.nan
            rows.append((ty, len(tr), len(te), a, brier, wr(te), te.r_net.sum()))
        results[name] = rows

    wlog("## Expanding walk-forward (обучение на всех прошлых годах)\n")
    wlog("| модель | OOS год | n_train(tp/sl) | n_test | AUC | Brier | WR(test) | ΣR(test) |")
    wlog("|---|---|---|---|---|---|---|---|")
    for name, rows in results.items():
        for ty, ntr, nte, a, br, w_, sr in rows:
            wlog(f"| {name} | {ty} | {ntr} | {nte} | {a:.3f} | {br:.3f} | {w_:.1f}% | {sr:+.1f} |")

    # ===== деталь по главным годам (2024/2025): калибровка + бакеты =====
    for name in ("base11", "ext16"):
        pcol = f"p_{name}"
        for ty in (2024, 2025, 2026):
            te = df[(df.year == ty) & df[pcol].notna()].copy()
            d = te[te.outcome.isin(["tp", "sl"])].copy()
            if len(d) < 20:
                continue
            d["q"] = pd.qcut(d[pcol], min(5, max(2, len(d) // 25)), duplicates="drop")
            wlog(f"\n### {name} — OOS {ty}: калибровка по квинтилям (tp/sl n={len(d)})")
            wlog("| бакет p | n | средняя p | факт WR |")
            wlog("|---|---|---|---|")
            for q, g in d.groupby("q", observed=True):
                wlog(f"| {q} | {len(g)} | {g[pcol].mean():.3f} | {100*(g.outcome=='tp').mean():.1f}% |")
            # практика: пороги
            wlog(f"\n### {name} — OOS {ty}: эффект порогов (по всем исходам года)")
            wlog("| отбор | n | WR | AvgR | ΣR |")
            wlog("|---|---|---|---|---|")
            for label, mask in (
                ("все", te.index == te.index),
                (f"p>=0.5", te[pcol] >= 0.5),
                (f"p>=0.6", te[pcol] >= 0.6),
                (f"p<0.5 (низ)", te[pcol] < 0.5),
            ):
                sub = te[mask] if not isinstance(mask, pd.Series) else te[mask]
                wlog(f"| {label} | {len(sub)} | {wr(sub):.1f}% | {sub.r_net.mean():+.3f} | {sub.r_net.sum():+.1f} |")
            # терцили
            lo, hi = d[pcol].quantile([1/3, 2/3])
            for lab, mm in (("нижний терциль p", te[pcol] <= lo), ("верхний терциль p", te[pcol] >= hi)):
                sub = te[mm]
                wlog(f"| {lab} | {len(sub)} | {wr(sub):.1f}% | {sub.r_net.mean():+.3f} | {sub.r_net.sum():+.1f} |")

    # ===== сводный OOS-пул 2024–2026 =====
    wlog("\n## Сводный OOS-пул 2024–2026 (в каждом году модель училась только на прошлом)\n")
    wlog("| модель | n(tp/sl) | AUC | Brier | WR | AvgR(все) | ΣR(все) |")
    wlog("|---|---|---|---|---|---|---|")
    for name in ("base11", "ext16"):
        pcol = f"p_{name}"
        te = df[(df.year >= 2024) & df[pcol].notna()]
        d = te[te.outcome.isin(["tp", "sl"])]
        a = auc(d.y.to_numpy(), df.loc[d.index, pcol].to_numpy())
        br = float(np.mean((df.loc[d.index, pcol] - d.y) ** 2))
        wlog(f"| {name} | {len(d)} | {a:.3f} | {br:.3f} | {wr(te):.1f}% | {te.r_net.mean():+.3f} | {te.r_net.sum():+.1f} |")
    for name in ("base11", "ext16"):
        pcol = f"p_{name}"
        te = df[(df.year >= 2024) & df[pcol].notna()].copy()
        lo, hi = te[pcol].quantile([1 / 3, 2 / 3])
        wlog(f"- {name} 2024–26: нижний терциль p: WR {wr(te[te[pcol] <= lo]):.1f}% avg {te[te[pcol] <= lo].r_net.mean():+.3f} | "
             f"верхний терциль p: WR {wr(te[te[pcol] >= hi]):.1f}% avg {te[te[pcol] >= hi].r_net.mean():+.3f}")

    # ===== коэффициенты (train 2020-2024 -> для отчёта) =====
    wlog("\n## Коэффициенты base11 (train 2020–2024, OOS=2025)\n")
    tr = df[(df.year < 2025) & df.y.notna()]
    mu = tr[BASE11].astype(float).mean()
    sd = tr[BASE11].astype(float).std().replace(0, 1.0)
    ztr = ((tr[BASE11].astype(float) - mu) / sd).clip(-6, 6).fillna(0.0)
    Xtr = np.c_[np.ones(len(tr)), ztr.to_numpy(float)]
    w, se = fit_lr(Xtr, tr.y.to_numpy(float))
    wlog("| признак | вес (log-odds на 1σ) | SE | z |")
    wlog("|---|---|---|---|")
    names = ["const"] + BASE11
    for i, nm in enumerate(names):
        wlog(f"| {nm} | {w[i]:+.3f} | {se[i]:.3f} | {w[i]/se[i]:+.2f} |")
    wlog(f"\nнормировка: mean/std по train-годам; например `vd`: mu={mu['vd']:.4f} sd={sd['vd']:.4f}; "
         f"`liquidity_distance`: mu={mu['liquidity_distance']:.4f} sd={sd['liquidity_distance']:.4f}; "
         f"`ema_slope_side`: mu={mu['ema_slope_side']:.4f} sd={sd['ema_slope_side']:.4f}")

    # ===== EMA-контроль: якорь (now) vs lag1 vs future =====
    wlog("\n## EMA-контроль (что было бы при подглядывании)\n")
    wlog("| вариант ema_slope | OOS 2025 AUC | вес черты |")
    wlog("|---|---|---|")
    for lab, col in (("now (закрыт <= from_ts)", "ema_slope_side"),
                     ("lag1 (на бар раньше)", "ema_slope_lag1"),
                     ("future (закрывается ПОСЛЕ from_ts — подглядывание)", "ema_slope_future")):
        feats = [c for c in BASE11 if c != "ema_slope_side"] + [col]
        _, _, p = zfit(df, feats, 2025)
        te = df[df.year == 2025]
        d = te[te.outcome.isin(["tp", "sl"])]
        a = auc(d.y.to_numpy(), p.reindex(d.index).to_numpy())
        tr2 = df[(df.year < 2025) & df.y.notna()]
        mu2 = tr2[feats].astype(float).mean(); sd2 = tr2[feats].astype(float).std().replace(0, 1.0)
        z2 = ((tr2[feats].astype(float) - mu2) / sd2).clip(-6, 6).fillna(0.0)
        w2, _ = fit_lr(np.c_[np.ones(len(tr2)), z2.to_numpy(float)], tr2.y.to_numpy(float))
        wlog(f"| {lab} | {a:.3f} | {w2[-1]:+.3f} (1σ={sd2[col]:.4f}) |")

    # ===== кандидаты по одной (univariate AUC на train 2020-2024) =====
    wlog("\n## Кандидаты-добавки: одиночный AUC (train 2020–2024, tp/sl)\n")
    tr = df[(df.year < 2025) & df.y.notna()]
    wlog("| кандидат | покрытие | AUC одномерно (train) | в модели |")
    wlog("|---|---|---|---|")
    for c in CANDS:
        if c not in df.columns:
            continue
        x = pd.to_numeric(tr[c], errors="coerce")
        cov_ = float(x.notna().mean())
        a = auc(tr.y.to_numpy(), x.to_numpy())
        tag = "base11" if c in BASE11 else ("ext16" if c in EXT16 else "—")
        wlog(f"| {c} | {cov_:.2f} | {a:.3f} | {tag} |")

    # ===== lam-устойчивость =====
    wlog("\n## Устойчивость к L2 (OOS 2025, AUC base11)\n")
    for lam in (0.3, 1.0, 3.0):
        _, _, p = zfit(df, BASE11, 2025, lam=lam)
        te = df[df.year == 2025]
        d = te[te.outcome.isin(["tp", "sl"])]
        a = auc(d.y.to_numpy(), p.reindex(d.index).to_numpy())
        wlog(f"- lam={lam}: AUC {a:.3f}")

    # сохранить предсказания
    keep = ["sym", "prof", "year", "dir", "outcome", "r_net", "from_ts", "hash", "y"] + \
           [f"p_{n}" for n in ("base11", "ext16")] + BASE11 + \
           ["slope_h1", "r1h", "of1_conf", "soft_dow", "bars_since_pivot", "ema_slope_lag1", "ema_slope_future"]
    df[keep].to_pickle(f"{BASE}/lr18_sol_pred.pkl")
    print("saved lr18_sol_pred.pkl")

    with open(f"{BASE}/lr18_sol_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(report))
    print("saved lr18_sol_report.md")
    # короткая сводка в stdout
    print("\n".join(report[:8]))
    for name in ("base11", "ext16"):
        for ty, ntr, nte, a, br, w_, sr in results[name]:
            print(f"{name} {ty}: ntr={ntr} nte={nte} AUC={a:.3f} WR={w_:.1f}% SR={sr:+.1f}")


if __name__ == "__main__":
    main()
