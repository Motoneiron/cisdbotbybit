# -*- coding: utf-8 -*-
"""LR-формула для SOL: подготовка фич на честном якоре (закрытые бары к from_ts).

Фичи: вектор 18-го (11) + кандидаты расширения. Только ЧТЕНИЕ потоков,
пишет новые файлы lr18_sol_*. Ничего существующего не трогает.

Якорь: последний ПОЛНОСТЬЮ закрытый бар главного ТФ к from_ts:
  ii = searchsorted(ts, from_ts - tfm, 'right') - 1   (канон lookahead-traps п.11)
Контроль: assert close(bar_ii) <= from_ts; рядом сохраняются lag1 и future-варианты EMA.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def process_group(sol, idx, prof, year):
    tf = "5m" if prof == "tf7" else "30m"
    tfm = 5 if prof == "tf7" else 30
    dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol="SOL")
    dft.index = pd.DatetimeIndex(dft.index)
    ts = dft.index.to_numpy()
    n = len(dft)
    atr = compute_atr14(dft).to_numpy(float)
    c = dft["close"].astype(float)
    ema8 = c.ewm(span=8, min_periods=8, adjust=False).mean().to_numpy(float)
    ema21 = c.ewm(span=21, min_periods=21, adjust=False).mean().to_numpy(float)

    fts = sol.loc[idx, "from_ts"]
    ii = np.searchsorted(ts, (fts - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
    good = (ii >= 30) & (ii < n)
    pos = np.where(good, ii, 0)

    # --- строгий контроль якоря: бар закрыт не позже from_ts ---
    close_time = pd.DatetimeIndex(ts[pos]) + pd.Timedelta(minutes=tfm)
    gt = (fts.values > close_time.values) | (fts.values == close_time.values)
    viol = int((good & ~gt).sum())
    gaps = ((fts.values - close_time.values) / np.timedelta64(1, "m"))[good]

    ent = sol.loc[idx, "entry"].to_numpy(float)
    stp = sol.loc[idx, "stop"].to_numpy(float)
    dirs = sol.loc[idx, "dir"].to_numpy(str)

    atr_g = np.where(good & (atr[pos] > 0), atr[pos], np.nan)
    ld = np.abs(ent - stp) / atr_g
    slope = (ema8[pos] - ema21[pos]) / atr_g
    side = np.where(dirs == "LONG", slope, -slope)

    # контрольные варианты EMA-меры (lag1 = точно доступно; future = подглядывание)
    sl_lag = np.full(len(idx), np.nan)
    sl_fut = np.full(len(idx), np.nan)
    ok_l = (ii - 1) >= 30
    ok_f = (ii + 1) < n
    pl, pf = np.clip(ii - 1, 0, n - 1), np.clip(ii + 1, 0, n - 1)
    atr_l = np.where(atr[pl] > 0, atr[pl], np.nan)
    atr_f = np.where(atr[pf] > 0, atr[pf], np.nan)
    v_l = (ema8[pl] - ema21[pl]) / atr_l
    v_f = (ema8[pf] - ema21[pf]) / atr_f
    m = good & ok_l
    sl_lag[m] = np.where(dirs[m] == "LONG", v_l[m], -v_l[m])
    m = good & ok_f
    sl_fut[m] = np.where(dirs[m] == "LONG", v_f[m], -v_f[m])
    # gap бара в минутах (>=0)
    return viol, gaps, ld, side, sl_lag, sl_fut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    df = pd.read_pickle(f"{BASE}/knn18_live_full.pkl")
    sol = df[df.sym == "SOL"].copy().reset_index(drop=True)
    sol["from_ts"] = pd.to_datetime(sol["from_ts"])
    print(f"SOL rows: {len(sol)}")
    print("outcome:", sol.outcome.value_counts().to_dict())
    print("prof:", sol["prof"].value_counts().to_dict())
    print("dir:", sol["dir"].value_counts().to_dict())
    print("по годам:", sol.groupby("year").size().to_dict())

    for c in ["liquidity_distance", "ema_slope_side", "ema_slope_lag1", "ema_slope_future"]:
        sol[c] = np.nan
    sol["bar_gap_min"] = np.nan

    t0 = time.time()
    total_viol = 0
    all_gaps = []
    groups = list(sol.groupby(["prof", "year"]).groups.items())
    if args.smoke:
        groups = [g for g in groups if g[0][0] == "tf7" and g[0][1] == 2024]
    for (prof, year), idx in groups:
        idx = pd.Index(idx)
        t1 = time.time()
        viol, gaps, ld, side, sl_lag, sl_fut = process_group(sol, idx, prof, year)
        sol.loc[idx, "liquidity_distance"] = ld
        sol.loc[idx, "ema_slope_side"] = side
        sol.loc[idx, "ema_slope_lag1"] = sl_lag
        sol.loc[idx, "ema_slope_future"] = sl_fut
        sol.loc[idx, "bar_gap_min"] = gaps
        total_viol += viol
        all_gaps.extend(gaps.tolist())
        print(f"  [{prof} {year}] n={len(idx)} viol={viol} gap[min..med..max]="
              f"{gaps.min():.1f}..{np.median(gaps):.1f}..{gaps.max():.1f}  ({time.time()-t1:.1f}s)")
    print(f"ИТОГО: нарушений якоря {total_viol} (должно быть 0); время {time.time()-t0:.1f}s")
    if all_gaps:
        print(f"зазоры from_ts - close(bar): мин {min(all_gaps):.1f} мин, медиана {np.median(all_gaps):.1f} мин")

    if not args.smoke:
        # sanity: |entry-stop| vs sp*entry
        d1 = (sol.entry - sol.stop).abs()
        d2 = sol.sp * sol.entry
        rel = ((d1 - d2).abs() / d1.clip(lower=1e-12))
        print(f"sanity |entry-stop| vs sp*entry: max rel diff {rel.max():.2e}")
        cols_keep = ["sym", "prof", "year", "dir", "outcome", "r_net", "entry", "stop", "tp", "sp",
                     "vd", "sweep_atr", "vol_ratio", "vol_ratio_scan", "quality_score", "prior_touches",
                     "stoch_k", "macd_hist", "ema_distance_atr", "atr_percentile",
                     "liquidity_distance", "ema_slope_side", "ema_slope_lag1", "ema_slope_future",
                     "bar_gap_min", "from_ts", "ts_fill", "exit_ts", "hash",
                     "rr_planned", "psl_probability", "psl_quartile", "soft_dow", "late_retest",
                     "one_bar_sweep_cisd", "confirm_on_sweep", "fib_stretch_market",
                     "q_start_n", "q_never", "q_unreclaim", "q_no_start_fvg", "q_no_conf_fvg",
                     "bars_since_pivot"]
        out = sol[cols_keep]
        out.to_pickle(f"{BASE}/lr18_sol_feats.pkl")
        print(f"saved lr18_sol_feats.pkl  {out.shape}")
        # быстрый отчёт
        with open(f"{BASE}/lr18_sol_prep_report.txt", "w", encoding="utf-8") as fh:
            fh.write(f"SOL rows: {len(out)}\n")
            fh.write(f"якорь: нарушений {total_viol}; зазоры мин {min(all_gaps):.2f} / медиана {np.median(all_gaps):.2f} мин\n")
            fh.write("NaN по новым фичам:\n")
            for c in ["liquidity_distance", "ema_slope_side", "ema_slope_lag1", "ema_slope_future", "bar_gap_min"]:
                fh.write(f"  {c}: {int(out[c].isna().sum())}\n")
            fh.write("\ndescribe ключевых фич:\n")
            fh.write(out[["liquidity_distance", "ema_slope_side", "sweep_atr", "vd", "sp", "rr_planned"]]
                     .describe().to_string())
            fh.write("\n")
        print("saved lr18_sol_prep_report.txt")


if __name__ == "__main__":
    main()
