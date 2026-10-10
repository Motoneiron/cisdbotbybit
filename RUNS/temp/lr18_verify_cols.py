# -*- coding: utf-8 -*-
"""Сверка колонок vd/stoch/vol: чем реально считались фичи (close vs hlc3 vwap).

Пересчитывает заново на баре ii (закрыт <= from_ts) для всех групп SOL и сравнивает
с колонками в lr18_sol_feats.pkl. Только чтение.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "D:/PYTHON")
sys.path.insert(0, "D:/PYTHON/CISDBOT")
from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from backtest.stoch_filter import slow_stochastic
from backtest.volume_filter import volume_ratio_series
from backtest.vwap_filter import daily_session_vwap as vw_close_ver  # текущая CISDBOT (close)

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def vw_hlc3(df):
    typ = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    pv = typ * df["volume"]
    day = df.index.floor("D")
    vol_cum = df["volume"].groupby(day).cumsum()
    pv_cum = pv.groupby(day).cumsum()
    return pv_cum / vol_cum


def main():
    feats = pd.read_pickle(f"{BASE}/lr18_sol_feats.pkl")
    feats = feats.reset_index(drop=True)
    out = feats[["prof", "year", "from_ts"]].copy()
    for c in ["vd_close", "vd_hlc3", "stoch_chk", "vol_chk"]:
        out[c] = np.nan

    for (prof, year), idx in feats.groupby(["prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol="SOL")
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        atr = compute_atr14(dft).to_numpy(float)
        cl = dft["close"].astype(float).to_numpy(float)
        vwc = vw_close_ver(dft).to_numpy(float)
        vwh = vw_hlc3(dft).to_numpy(float)
        st = slow_stochastic(dft)["stoch_k"].to_numpy(float)
        vr = volume_ratio_series(dft, 20).to_numpy(float)
        fts = pd.to_datetime(feats.loc[idx, "from_ts"])
        ii = np.searchsorted(ts, (fts - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
        good = (ii >= 30) & (ii < len(dft))
        pos = np.where(good, ii, 0)
        out.loc[idx, "vd_close"] = np.where(good & (atr[pos] > 0), (cl[pos] - vwc[pos]) / atr[pos], np.nan)
        out.loc[idx, "vd_hlc3"] = np.where(good & (atr[pos] > 0), (cl[pos] - vwh[pos]) / atr[pos], np.nan)
        out.loc[idx, "stoch_chk"] = np.where(good, st[pos], np.nan)
        out.loc[idx, "vol_chk"] = np.where(good, vr[pos], np.nan)
        print(f"[{prof} {year}] ok", flush=True)

    out["vd_saved"] = feats["vd"].to_numpy()
    out["stoch_saved"] = feats["stoch_k"].to_numpy()
    out["vol_saved"] = feats["vol_ratio_scan"].to_numpy()

    def cmp(name, a, b):
        m = out[a].notna() & out[b].notna()
        d = (out.loc[m, a] - out.loc[m, b]).abs()
        close_share = float((d < 1e-4).mean())
        med = float(d.median())
        mx = float(d.max())
        # корреляция рангов
        cc = float(np.corrcoef(out.loc[m, a].rank(), out.loc[m, b].rank())[0, 1])
        print(f"{name:28s} n={int(m.sum()):4d} | |diff|<1e-4: {100*close_share:5.1f}% | med {med:.2e} | max {mx:.2e} | rankcorr {cc:.4f}")

    print()
    cmp("vd_saved vs vd_close", "vd_close", "vd_saved")
    cmp("vd_saved vs vd_hlc3", "vd_hlc3", "vd_saved")
    cmp("stoch_saved vs stoch_chk", "stoch_chk", "stoch_saved")
    cmp("vol_saved vs vol_chk", "vol_chk", "vol_saved")

    print()
    print("по профилям (vd_saved vs vd_close / vd_hlc3), доля совпадений <1e-4:")
    for prof in ("tf7", "tf8"):
        sub = out[out.prof == prof]
        for a, b in (("vd_close", "vd_saved"), ("vd_hlc3", "vd_saved")):
            m = sub[a].notna() & sub[b].notna()
            d = (sub.loc[m, a] - sub.loc[m, b]).abs()
            print(f"  {prof}: {a}: {100*float((d < 1e-4).mean()):5.1f}%  (n={int(m.sum())})")


if __name__ == "__main__":
    main()
