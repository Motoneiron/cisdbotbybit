"""Добавляет к снапшоту потока фичи вектора 18-го (cf-определения) на главном ТФ в scan-баре.

Cols: stoch_k (14-3), macd_hist (12-26-9), ema_distance_atr ((close-EMA20)/ATR14),
atr_percentile (перцентиль ewm14(H-L) по 100 барам), vol_ratio_scan (vol/SMA20 в scan-баре).
Использование: python _stream_vector_v2.py <stream_pkl> [--out <out_pkl>]"""
import argparse
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.macd_filter import macd_frame
from backtest.stoch_filter import slow_stochastic
from backtest.sweep_atr_filter import compute_atr14
from backtest.volume_filter import volume_ratio_series

NEW = ["stoch_k", "macd_hist", "ema_distance_atr", "atr_percentile", "vol_ratio_scan"]


def pct_rank(series: pd.Series, i: int, lookback: int = 100):
    window = series.iloc[: i + 1].dropna().iloc[-lookback:]
    if len(window) < 10:
        return None
    cur = float(window.iloc[-1])
    if not np.isfinite(cur):
        return None
    return float((window <= cur).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stream", nargs="?", default=r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_off_v1.pkl")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or args.stream.replace(".pkl", "_v2.pkl")
    df = pd.read_pickle(args.stream)
    for c in NEW:
        df[c] = np.nan
    if "decision_at" not in df.columns or "exit_ts" not in df.columns:
        print("WARN: нет decision_at/exit_ts — пересобери снапшот патченным билдером (только для колонок kNN)")
    cnt = 0
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        dft, _ = load_ltf(tf=tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        n = len(dft)
        st = slow_stochastic(dft)["stoch_k"].to_numpy(float)
        mh = macd_frame(dft)["macd_hist"].to_numpy(float)
        ema20 = dft["close"].ewm(span=20, adjust=False, min_periods=20).mean().to_numpy(float)
        atr = compute_atr14(dft).to_numpy(float)
        close = dft["close"].astype(float).to_numpy()
        rng = (dft["high"].astype(float) - dft["low"].astype(float)).ewm(span=14, min_periods=14).mean()
        vr = volume_ratio_series(dft, 20).to_numpy(float)
        sub = df.loc[idx]
        sb_num = pd.to_numeric(sub["scan_bar"], errors="coerce")
        sb_i = sb_num.fillna(-1).astype("int64").to_numpy()
        good = (sb_i >= 0) & (sb_i < n)
        pos = np.where(good, sb_i, 0)
        df.loc[idx, "stoch_k"] = np.where(good, st[pos], np.nan)
        df.loc[idx, "macd_hist"] = np.where(good, mh[pos], np.nan)
        df.loc[idx, "ema_distance_atr"] = np.where(good & np.isfinite(atr[pos]) & (atr[pos] != 0), (close[pos] - ema20[pos]) / atr[pos], np.nan)
        df.loc[idx, "vol_ratio_scan"] = np.where(good, vr[pos], np.nan)
        vals = np.full(len(sub), np.nan)
        for k_, i_ in enumerate(sb_i):
            if 0 <= i_ < n:
                v = pct_rank(rng, int(i_))
                if v is not None:
                    vals[k_] = v
        df.loc[idx, "atr_percentile"] = vals
        cnt += 1
    df.to_pickle(out)
    print("saved:", out, "| rows:", len(df), "| groups:", cnt)
    for c in NEW:
        print(f"  {c}: notna={df[c].notna().sum()}/{len(df)}")


if __name__ == "__main__":
    main()
