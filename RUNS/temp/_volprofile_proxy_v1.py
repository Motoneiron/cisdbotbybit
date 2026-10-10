"""Volume Profile proxy v1: объём-по-ценам из HTF-баров (равномерно в H-L) → фичи к потоку.

Для каждой сделки: окно последних N HTF-баров до decision (~25 дней на 4H), 50 bins.
Фичи: vp_poc_atr ((entry-POC)/ATR), vp_va_pos (позиция entry в Value Area 70%),
vp_block_share (доля объёма на пути entry→TP1 в «толстых» bins >1.5×медианы),
vp_width_atr (ширина VA в ATR). Допущение: объём бара равномерен по H-L (proxy).
Использование: python _volprofile_proxy_v1.py <stream_v2_pkl> [--tag vp] [--nwin 150]
"""
import argparse
import bisect
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14

NEW = ["vp_poc_atr", "vp_va_pos", "vp_block_share", "vp_width_atr"]


def profile_features(bars, entry, tp1, atr_v):
    hi = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    vol = bars["volume"].to_numpy(float)
    pmin, pmax = float(lo.min()), float(hi.max())
    if not (pmax > pmin) or not np.isfinite(atr_v) or atr_v <= 0:
        return None
    nbins = 50
    edges = np.linspace(pmin, pmax, nbins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    hist = np.zeros(nbins)
    for i in range(len(bars)):
        l_, h_, v_ = lo[i], hi[i], vol[i]
        if not np.isfinite(v_) or v_ <= 0 or h_ <= l_:
            continue
        b0 = max(0, int(np.searchsorted(edges, l_, side="right")) - 1)
        b1 = min(nbins - 1, int(np.searchsorted(edges, h_, side="left")) - 1)
        if b1 < b0:
            continue
        seg = b1 - b0 + 1
        hist[b0 : b1 + 1] += v_ / seg
    if hist.sum() <= 0:
        return None
    poc = float(centers[int(np.argmax(hist))])
    order = np.argsort(hist)[::-1]
    target = 0.7 * hist.sum()
    acc = 0.0
    va = []
    for oi in order:
        acc += hist[oi]
        va.append(int(oi))
        if acc >= target:
            break
    va_lo = float(edges[min(va)])
    va_hi = float(edges[max(va) + 1])
    va_pos = (entry - va_lo) / (va_hi - va_lo) if va_hi > va_lo else 0.5
    lo_px, hi_px = (entry, tp1) if tp1 > entry else (tp1, entry)
    pos_hist = hist[hist > 0]
    m = float(np.median(pos_hist)) if len(pos_hist) else 0.0
    inpath = np.where(hist > 1.5 * m, hist, 0.0)
    idx = (centers >= lo_px) & (centers <= hi_px)
    path_vol = float(hist[idx].sum())
    block_vol = float(inpath[idx].sum())
    return {
        "vp_poc_atr": (entry - poc) / atr_v,
        "vp_va_pos": va_pos,
        "vp_block_share": (block_vol / path_vol) if path_vol > 0 else None,
        "vp_width_atr": (va_hi - va_lo) / atr_v,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stream")
    ap.add_argument("--tag", default="vp")
    ap.add_argument("--nwin", type=int, default=150)
    args = ap.parse_args()
    df = pd.read_pickle(args.stream)
    for c in NEW:
        df[c] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        rule = "4h" if prof == "tf7" else "8h"
        dft, _ = load_ltf(tf=tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        htf = pd.DataFrame(
            {
                "high": dft["high"].resample(rule, label="left", closed="left").max(),
                "low": dft["low"].resample(rule, label="left", closed="left").min(),
                "close": dft["close"].resample(rule, label="left", closed="left").last(),
                "volume": dft["volume"].resample(rule, label="left", closed="left").sum(),
            }
        ).dropna()
        atr = compute_atr14(htf)
        ht_idx = list(htf.index)
        for r_i, row in df.loc[idx].iterrows():
            dec = pd.Timestamp(str(row["decision_at"]))
            k = bisect.bisect_left(ht_idx, dec)
            if k < 30:
                continue
            bars = htf.iloc[max(0, k - args.nwin) : k]
            a = float(atr.iloc[k - 1]) if k >= 1 and pd.notna(atr.iloc[k - 1]) else np.nan
            entry = float(row["entry"])
            stop = float(row["stop"])
            tp1 = entry + (entry - stop) if row["dir"] == "LONG" else entry - (stop - entry)
            feats = profile_features(bars, entry, tp1, a)
            if feats:
                for c2, v2 in feats.items():
                    df.at[r_i, c2] = v2
    out = args.stream.replace(".pkl", f"_{args.tag}.pkl")
    df.to_pickle(out)
    print(f"saved: {out}", flush=True)
    s = df[df["vp_poc_atr"].notna()]

    def line(name, part):
        dec = part[part["outcome"].isin(["tp", "sl"])]
        w = 100.0 * (dec["outcome"] == "tp").mean() if len(dec) else 0.0
        print(f"{name:30s} n={len(part):5d} WR={w:5.1f}% ΣR={part['r_net'].sum():8.1f} AvgR={part['r_net'].mean() if len(part) else 0:6.3f}", flush=True)

    line("ALL (с VP)", s)
    for d in ("SHORT", "LONG"):
        g = s[s["dir"] == d]
        if len(g):
            line(f"{d} ALL", g)
    print("-- vp_block_share квартили --", flush=True)
    q = s[s["vp_block_share"].notna()].copy()
    if len(q):
        q["qb"] = pd.qcut(q["vp_block_share"].rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
        for b, g in q.groupby("qb", observed=True):
            line(f"block_share {b}", g)
    print("-- vp_va_pos бакеты --", flush=True)
    for lo_, hi_ in [(-9, 0), (0, 0.25), (0.25, 0.75), (0.75, 1.01), (1.01, 9)]:
        g = s[(s["vp_va_pos"] >= lo_) & (s["vp_va_pos"] < hi_)]
        if len(g):
            line(f"va_pos [{lo_},{hi_})", g)


if __name__ == "__main__":
    main()
