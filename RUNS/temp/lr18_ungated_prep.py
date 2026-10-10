# -*- coding: utf-8 -*-
"""Фичи LR-формул на ГОЛОМ потоке (ungated): SOL.

Поток: stream_ungated_v2.pkl (LIMIT, filters-off, без vwap-гейта, min_stop 0.25%, TP1R, Bybit).
Фичи считаются 1:1 как в v2-серии:
  - из сигналов кэшей filters_off_full (по hash): quality_score, prior_touches,
    sweep_atr (sweep_atr_ratio на глобальном trigger-баре), t_sw=confirm-trigger;
  - индикаторные на якоре «последний закрытый бар к from_ts»: stoch_k, macd_hist,
    ema_distance_atr=(close-EMA20)/ATR14, atr_percentile (перцентиль ewm14(H-L) по 100),
    vol_ratio_scan=vol/SMA20; liquidity_distance=|entry-stop|/ATR; ema_slope_side=±(EMA8-EMA21)/ATR;
  - vd = vd_conf из ungated.
SANITY: пересечение с knn18_live_full по (hash,prof) — сверка значений 1:1.
Выход: lr18_ungated_feats.pkl. Только чтение чужих файлов.
"""
from __future__ import annotations

import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.macd_filter import macd_frame
from backtest.stoch_filter import slow_stochastic
from backtest.sweep_atr_filter import compute_atr14, sweep_atr_ratio
from backtest.volume_filter import volume_ratio_series

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
CDIR = r"D:/PYTHON/CISDBOT/RUNS/filters_off_full"
WINDOW = 200


def _num(v):
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def trig_global(scan_bar, trigger_idx, n):
    if scan_bar is None or trigger_idx is None:
        return None
    gi = max(0, int(scan_bar) - (WINDOW - 1)) + int(trigger_idx)
    return gi if 0 <= gi < n else None


def pct_rank(series, i, lookback=100):
    w = series.iloc[: i + 1].dropna().iloc[-lookback:]
    if len(w) < 10:
        return None
    cur = float(w.iloc[-1])
    if not np.isfinite(cur):
        return None
    return float((w <= cur).mean())


def main():
    df = pd.read_pickle(f"{BASE}/stream_ungated_v2.pkl")
    df = df[df.sym == "SOL"].copy().reset_index(drop=True)
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    print(f"ungated SOL: {len(df)} rows | prof {df.prof.value_counts().to_dict()}", flush=True)
    print("outcome:", df.outcome.value_counts().to_dict(), flush=True)

    NEW = ["sweep_atr", "quality_score", "prior_touches", "t_sw_min",
           "stoch_k", "macd_hist", "ema_distance_atr", "atr_percentile", "vol_ratio_scan",
           "liquidity_distance", "ema_slope_side"]
    for c in NEW:
        df[c] = np.nan

    t0 = time.time()
    n_match = 0
    for (prof, year), idx in df.groupby(["prof", "year"]).groups.items():
        idx = pd.Index(idx)
        path = f"{CDIR}/SOL_{prof}_{year}-01-01_{year}-12-31.pkl"
        with open(path, "rb") as fh:
            c = pickle.load(fh)
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol="SOL")
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        n = len(dft)
        atr = compute_atr14(dft)
        atr_arr = atr.to_numpy(float)
        close = dft["close"].astype(float).to_numpy(float)
        st = slow_stochastic(dft)["stoch_k"].to_numpy(float)
        mh = macd_frame(dft)["macd_hist"].to_numpy(float)
        ema20 = dft["close"].ewm(span=20, adjust=False, min_periods=20).mean().to_numpy(float)
        rng = (dft["high"].astype(float) - dft["low"].astype(float)).ewm(span=14, min_periods=14).mean()
        vr = volume_ratio_series(dft, 20).to_numpy(float)
        ema8 = dft["close"].ewm(span=8, adjust=False, min_periods=8).mean().to_numpy(float)
        ema21 = dft["close"].ewm(span=21, adjust=False, min_periods=21).mean().to_numpy(float)

        fts = df.loc[idx, "from_ts"]
        ii = np.searchsorted(ts, (fts - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
        good = (ii >= 30) & (ii < n)
        pos = np.where(good, ii, 0)
        close_time = pd.DatetimeIndex(ts[pos]) + pd.Timedelta(minutes=tfm)
        viol = int((good & ~((fts.values > close_time.values) | (fts.values == close_time.values))).sum())

        ent = df.loc[idx, "entry"].to_numpy(float)
        stp = df.loc[idx, "stop"].to_numpy(float)
        dirs = df.loc[idx, "dir"].to_numpy(str)
        atr_g = np.where(good & (atr_arr[pos] > 0), atr_arr[pos], np.nan)
        ld = np.abs(ent - stp) / atr_g
        slp = (ema8[pos] - ema21[pos]) / atr_g
        side = np.where(dirs == "LONG", slp, -slp)

        df.loc[idx, "stoch_k"] = np.where(good, st[pos], np.nan)
        df.loc[idx, "macd_hist"] = np.where(good, mh[pos], np.nan)
        df.loc[idx, "ema_distance_atr"] = np.where(good & np.isfinite(atr_arr[pos]) & (atr_arr[pos] != 0),
                                                   (close[pos] - ema20[pos]) / atr_arr[pos], np.nan)
        df.loc[idx, "vol_ratio_scan"] = np.where(good, vr[pos], np.nan)
        df.loc[idx, "liquidity_distance"] = ld
        df.loc[idx, "ema_slope_side"] = side
        vals = np.full(len(idx), np.nan)
        for k_, i_ in enumerate(ii):
            if 0 <= i_ < n:
                v = pct_rank(rng, int(i_))
                if v is not None:
                    vals[k_] = v
        df.loc[idx, "atr_percentile"] = vals

        # фичи из сигналов
        miss = 0
        for k_, (row_i, hsh) in enumerate(zip(idx, df.loc[idx, "hash"].astype(str))):
            s = sigs.get(hsh)
            if not s:
                miss += 1
                continue
            n_match += 1
            qs = _num(s.get("quality_score"))
            pt = _num(s.get("prior_touches"))
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            tbt = pd.Timestamp(str(s.get("trigger_bar_time")))
            df.at[row_i, "quality_score"] = qs
            df.at[row_i, "prior_touches"] = pt
            df.at[row_i, "t_sw_min"] = (cbt - tbt).total_seconds() / 60.0
            gi = trig_global(s.get("scan_bar"), s.get("trigger_idx"), n)
            if gi is not None:
                lvl = _num(s.get("htf_sweep_level"))
                if lvl and lvl > 0:
                    sw = sweep_atr_ratio(dft, gi, lvl, dirs[k_] == "SHORT", atr14=atr)
                    if sw is not None:
                        df.at[row_i, "sweep_atr"] = round(sw, 4)
        print(f"  [SOL {prof} {int(year)}] n={len(idx)} match={len(idx)-miss} miss={miss} "
              f"viol={viol} ({time.time()-t0:.0f}s)", flush=True)

    print(f"ИТОГО match сигналов: {n_match}/{len(df)}", flush=True)
    df["t_h"] = df["t_sw_min"] / 60.0
    df["t_log"] = np.log1p(df["t_sw_min"])
    df["t_bin"] = (df["t_sw_min"] >= 120).astype(float)
    df["y"] = np.where(df.outcome == "tp", 1.0, np.where(df.outcome == "sl", 0.0, np.nan))

    df.to_pickle(f"{BASE}/lr18_ungated_feats.pkl")
    print(f"saved lr18_ungated_feats.pkl {df.shape}", flush=True)

    print("\nNaN по фичам:", flush=True)
    for c in NEW + ["t_h", "t_log"]:
        print(f"  {c}: {int(df[c].isna().sum())}/{len(df)}", flush=True)

    # ---- SANITY: сверка с v2 (knn18_live_full) на пересечении ----
    v2 = pd.read_pickle(f"{BASE}/knn18_live_full.pkl")
    k = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
    v2i = v2.set_index(k(v2))
    u = df.set_index(k(df))
    common = u.index.intersection(v2i.index)
    print(f"\nSANITY vs v2: пересечение {len(common)} из {len(u)} ungated-SOL", flush=True)
    checks = [("vd_conf", "vd", 5e-5), ("quality_score", "quality_score", 5e-5),
              ("prior_touches", "prior_touches", 1e-9), ("stoch_k", "stoch_k", 1e-5),
              ("macd_hist", "macd_hist", 1e-7), ("ema_distance_atr", "ema_distance_atr", 1e-5),
              ("atr_percentile", "atr_percentile", 1e-9),
              ("liquidity_distance", "liquidity_distance", 1e-5),
              ("ema_slope_side", "ema_slope_side", 1e-5)]
    for cc, vc, tol in checks:
        a = u.loc[common, cc].astype(float)
        b = v2i.loc[common, vc].astype(float)
        ok = a.notna() & b.notna()
        m = (a[ok] - b[ok]).abs() <= tol
        print(f"  {cc:18} vs v2.{vc:18}: match {int(m.sum())}/{int(ok.sum())} = {100*m.mean():.2f}%", flush=True)
    # t_sw сверка (в v2: cbt-tbt из knn-колонок)
    a = u.loc[common, "t_sw_min"].astype(float)
    b = (pd.to_datetime(v2i.loc[common, "confirm_bar_time"]) - pd.to_datetime(v2i.loc[common, "trigger_bar_time"])).dt.total_seconds() / 60.0
    ok = a.notna() & b.notna()
    m = (a[ok] - b[ok]).abs() <= 1e-9
    print(f"  {'t_sw_min':18} vs v2 cbt-tbt           : match {int(m.sum())}/{int(ok.sum())} = {100*m.mean():.2f}%", flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
