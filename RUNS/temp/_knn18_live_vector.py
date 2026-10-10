"""Вектор 18-го на ЖИВОМ якоре: 5 индикаторных фич + vd считаем на закрытом баре к from_ts.

Популяция = тот же гейт-поток, что и раньше (stream_off_v1_lv0_v2_el.pkl, 25 230 сд) — чтобы
сравнение с прошлым замером было прямым. sweep_atr и quality_score берём как есть: обе
считаются ДО конфирма (геометрия свипа + FVG/never/bars1 между trigger и confirm) → от якоря
не зависят. Пересчитываем только зависящие от момента: stoch_k, macd_hist, ema_distance_atr,
atr_percentile, vol_ratio_scan, vd (vwap_deviation_atr).

Выход: knn18_live_input.pkl (колонки для _knn18_v1.py: vd, vol_ratio_scan, ...).
"""
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
from backtest.vwap_filter import daily_session_vwap

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
NEW = ["stoch_k", "macd_hist", "ema_distance_atr", "atr_percentile", "vol_ratio_scan", "vd"]


def pct_rank(series, i, lookback=100):
    w = series.iloc[: i + 1].dropna().iloc[-lookback:]
    if len(w) < 10:
        return None
    cur = float(w.iloc[-1])
    if not np.isfinite(cur):
        return None
    return float((w <= cur).mean())


def main():
    df = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_el.pkl").copy()
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    # vd: живой якорь — берём vd_conf из полного потока (тот же расчёт)
    full = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")[["hash", "prof", "vd_conf"]]
    k = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
    mp = dict(zip(k(full), full.vd_conf))
    df["vd"] = [mp.get(x) for x in k(df)]
    for c in ["stoch_k", "macd_hist", "ema_distance_atr", "atr_percentile", "vol_ratio_scan"]:
        df[c] = np.nan
    print(f"строк {len(df)}, vd_conf подтянут на {int(df.vd.notna().sum())}", flush=True)

    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        try:
            dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        except Exception as e:
            print(f"[{sym} {prof} {year}] load fail {e!r}", flush=True); continue
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        n = len(dft)
        st = slow_stochastic(dft)["stoch_k"].to_numpy(float)
        mh = macd_frame(dft)["macd_hist"].to_numpy(float)
        ema20 = dft["close"].ewm(span=20, adjust=False, min_periods=20).mean().to_numpy(float)
        atr = compute_atr14(dft).to_numpy(float)
        close = dft["close"].astype(float).to_numpy()
        rng = (dft["high"].astype(float) - dft["low"].astype(float)).ewm(span=14, min_periods=14).mean()
        vr = volume_ratio_series(dft, 20).to_numpy(float)
        vw = daily_session_vwap(dft).to_numpy(float)
        # индекс: последний ПОЛНОСТЬЮ закрытый бар к from_ts
        ii = np.searchsorted(ts, (df.loc[idx, "from_ts"] - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
        good = (ii >= 30) & (ii < n)
        pos = np.where(good, ii, 0)
        df.loc[idx, "stoch_k"] = np.where(good, st[pos], np.nan)
        df.loc[idx, "macd_hist"] = np.where(good, mh[pos], np.nan)
        df.loc[idx, "ema_distance_atr"] = np.where(good & np.isfinite(atr[pos]) & (atr[pos] != 0),
                                                   (close[pos] - ema20[pos]) / atr[pos], np.nan)
        df.loc[idx, "vol_ratio_scan"] = np.where(good, vr[pos], np.nan)
        if prof == "tf7":
            df.loc[idx, "vd"] = np.where(good & np.isfinite(atr[pos]) & (atr[pos] != 0),
                                         (close[pos] - vw[pos]) / atr[pos], df.loc[idx, "vd"])
        vals = np.full(len(idx), np.nan)
        for k_, i_ in enumerate(ii):
            if 0 <= i_ < n:
                v = pct_rank(rng, int(i_))
                if v is not None:
                    vals[k_] = v
        df.loc[idx, "atr_percentile"] = vals
        print(f"  [{sym} {prof} {int(year)}] ok", flush=True)

    df.to_pickle(f"{BASE}/knn18_live_input.pkl")
    print("saved knn18_live_input.pkl", flush=True)
    for c in NEW + ["sweep_atr", "quality_score"]:
        print(f"  {c}: notna={int(df[c].notna().sum())}/{len(df)}")
    print("\n=== сравнение старый якорь vs живой (медиана / corr rank) ===", flush=True)
    for c_new, c_old in [("stoch_k", "stoch_k"), ("macd_hist", "macd_hist"),
                         ("ema_distance_atr", "ema_distance_atr"), ("atr_percentile", "atr_percentile"),
                         ("vol_ratio_scan", "vol_ratio_scan"), ("vd", "vd")]:
        a = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_el.pkl")[[c_old]].iloc[:, 0]
        b = df[c_new]
        ok = a.notna() & b.notna()
        try:
            cc = np.corrcoef(a[ok].rank(), b[ok].rank())[0, 1]
        except Exception:
            cc = float("nan")
        print(f"  {c_new:18}: corr={cc:.3f}  медиана old={a[ok].median():+.4f} new={b[ok].median():+.4f}")
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
