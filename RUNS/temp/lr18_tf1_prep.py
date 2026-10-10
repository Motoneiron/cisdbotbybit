# -*- coding: utf-8 -*-
"""LR-формула на рабочем профиле tf1 (15m→4H): сборка фич + expanding walk-forward.

Датасеты (только чтение): stopt_df (822, до фильтра), stopt_v2_10pairs_final (998, рабочий, >=2ч).
Фичи из 1m→15m свечей на баре cbt (закрыт в cbt+15 = scan, каузально).
Выход: lr18_tf1_feats.pkl, lr18_tf1_report.md.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "D:/PYTHON")
sys.path.insert(0, "D:/PYTHON/CISDBOT")
from backtest.macd_filter import macd_frame
from backtest.stoch_filter import slow_stochastic
from backtest.sweep_atr_filter import compute_atr14
from backtest.volume_filter import volume_ratio_series
from backtest.vwap_filter import daily_session_vwap

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
    "BTC": r"D:\databtcusdt\BTCUSDT-1m\BTCUSDT_1m_2020_2026_conv.csv",
    "XRP": r"D:\databtcusdt\XRPUSDT-1m-merged.csv",
    "AVAX": r"D:\databtcusdt\AVAXUSDT-1m-merged.csv",
    "TON": r"D:\databtcusdt\TONUSDT-1m-merged.csv",
}

FEATS_ALL = ["t_log", "atr_percentile", "stoch_k", "macd_hist", "ema_dist_atr", "vd",
             "vol_ratio", "sp", "rr", "ph4h"]


def load_1m(path, since, until):
    t0 = pd.Timestamp(since) - pd.Timedelta(days=4)
    t1 = pd.Timestamp(until) + pd.Timedelta(days=1)
    parts = []
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    for chunk in pd.read_csv(path, usecols=cols, chunksize=500_000):
        ot = pd.to_datetime(chunk["open_time"], unit="ms")
        m = (ot >= t0) & (ot < t1)
        if not m.any():
            if len(ot) and ot.iloc[-1] < t0:
                continue
            if len(ot) and ot.iloc[0] >= t1:
                break
            continue
        sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
        sub.index = ot[m]
        parts.append(sub)
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def pct_rank(series, i, lookback=100):
    w = series.iloc[: i + 1].dropna().iloc[-lookback:]
    if len(w) < 10:
        return np.nan
    cur = float(w.iloc[-1])
    if not np.isfinite(cur):
        return np.nan
    return float((w <= cur).mean())


def main():
    d822 = pd.read_pickle(f"{BASE}/stopt_df.pkl")
    d822["src"] = "d822"
    d998 = pd.read_pickle(f"{BASE}/stopt_v2_10pairs_final.pkl")
    d998["src"] = "d998"
    both = pd.concat([d822, d998], ignore_index=True)
    for c in ("scan", "cbt", "tbt", "htf"):
        both[c] = pd.to_datetime(both[c])
    # dt_sw: восстановить везде (у новых пар пусто)
    both["dt_sw_calc"] = (both["cbt"] - both["tbt"]).dt.total_seconds() / 60.0
    both["year"] = both["scan"].dt.year
    both["t_h"] = both["dt_sw_calc"] / 60.0
    both["t_log"] = np.log1p(both["dt_sw_calc"])
    both["ph4h"] = (both["cbt"] - both["cbt"].dt.floor("4h")).dt.total_seconds() / 60.0
    both["rr"] = (both["tp"] - both["entry"]).abs() / (both["entry"] - both["stop"]).abs().clip(lower=1e-12)
    # atr_percentile и прочие считаются в цикле по парам (колонки создаются присваиванием)
    for c in ["atr_percentile", "stoch_k", "macd_hist", "ema_dist_atr", "vd", "vol_ratio", "liquidity_distance"]:
        both[c] = np.nan

    chunks = []
    for sym, idx in both.groupby("sym").groups.items():
        path = PATHS.get(sym)
        if path is None:
            print(f"[{sym}] no path", flush=True)
            continue
        df1 = load_1m(path, "2024-01-01", "2026-09-01")
        df15 = pd.DataFrame({
            "open": df1["open"].resample("15min", label="left", closed="left").first(),
            "high": df1["high"].resample("15min", label="left", closed="left").max(),
            "low": df1["low"].resample("15min", label="left", closed="left").min(),
            "close": df1["close"].resample("15min", label="left", closed="left").last(),
            "volume": df1["volume"].resample("15min", label="left", closed="left").sum(),
        }).dropna()
        ts = df15.index.to_numpy()
        atr = compute_atr14(df15)
        av = atr.to_numpy(float)
        cl = df15["close"].to_numpy(float)
        rng = (df15["high"].astype(float) - df15["low"].astype(float)).ewm(span=14, min_periods=14).mean()
        st = slow_stochastic(df15)["stoch_k"].to_numpy(float)
        mh = macd_frame(df15)["macd_hist"].to_numpy(float)
        e20 = df15["close"].astype(float).ewm(span=20, adjust=False, min_periods=20).mean().to_numpy(float)
        vw = daily_session_vwap(df15).to_numpy(float)
        vr = volume_ratio_series(df15, 20).to_numpy(float)
        cbt = both.loc[idx, "cbt"].to_numpy("datetime64[ns]")
        ii = np.searchsorted(ts, cbt, "right") - 1
        ok = (ii >= 30) & (ii < len(df15))
        # точное совпадение cbt с open бара:
        pos = np.clip(ii, 0, len(ts) - 1)
        match = ok & (ts[pos] == np.array(cbt))
        if not match.all():
            print(f"[{sym}] WARN: cbt не совпал с 15m-баром у {int((~match).sum())} строк", flush=True)
        g = match
        p = pos
        rng_a = rng.to_numpy(float)

        def pct_rank_arr(i, lookback=100):
            lo = max(0, i - lookback + 1)
            wv = rng_a[lo:i + 1]
            wv = wv[np.isfinite(wv)]
            if len(wv) < 10:
                return np.nan
            cur = rng_a[i]
            if not np.isfinite(cur):
                return np.nan
            return float((wv <= cur).mean())

        both.loc[idx[g], "atr_percentile"] = [pct_rank_arr(int(i)) for i in ii[g]]
        both.loc[idx[g], "stoch_k"] = np.where(g, st[ p], np.nan)[g]
        both.loc[idx[g], "macd_hist"] = np.where(g, mh[p], np.nan)[g]
        both.loc[idx[g], "ema_dist_atr"] = np.where(g & (av[p] > 0), (cl[p] - e20[p]) / av[p], np.nan)[g]
        both.loc[idx[g], "vd"] = np.where(g & (av[p] > 0), (cl[p] - vw[p]) / av[p], np.nan)[g]
        both.loc[idx[g], "vol_ratio"] = np.where(g, vr[p], np.nan)[g]
        both.loc[idx[g], "liquidity_distance"] = np.where(g & (av[p] > 0), (both.loc[idx[g], "entry"] - both.loc[idx[g], "stop"]).abs().to_numpy() / av[p], np.nan)
        print(f"[{sym}] ok n={len(idx)} (matched {int(g.sum())})", flush=True)

    # дубликаты строк (одна сделка в двух датасетах) — не мешают: аналитика по src
    both.to_pickle(f"{BASE}/lr18_tf1_feats.pkl")
    print("saved lr18_tf1_feats.pkl", both.shape)


if __name__ == "__main__":
    main()
