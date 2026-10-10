"""Проверка: отличается ли старый `zz_frac` от моего пересчёта на якоре decision_at?

Цель — исключить версию «в старом артефакте ДРУГАЯ формула frac» и оставить только
версию «дело в якоре». Считаю свой frac на decision_at (как старый) и сравниваю с
сохранёнными zz_frac/zz_last_dir из stream_off_v1_lv0_v2_el.pkl.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def zigzag(htf, atr, theta):
    pivots = []
    idx = htf.index
    h = htf["high"].to_numpy(float); l = htf["low"].to_numpy(float)
    c = htf["close"].to_numpy(float); a = atr.to_numpy(float)
    n = len(htf)
    if n < 3:
        return pivots
    dirn = 1 if c[1] >= c[0] else -1
    ext = h[1] if dirn == 1 else l[1]; ext_i = 1
    for i in range(2, n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if dirn == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif (ext - l[i]) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "up")); dirn, ext, ext_i = -1, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif (h[i] - ext) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "down")); dirn, ext, ext_i = 1, h[i], i
    return pivots


def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["SOL", "ADA", "BTC"]
    old = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_el.pkl")
    for (sym, prof), idx in old.groupby(["sym", "prof"]).groups.items():
        if sym not in syms:
            continue
        sub = old.loc[idx].copy()
        sub["decision_at"] = pd.to_datetime(sub["decision_at"])
        rule = "4h" if prof == "tf7" else "8h"
        for y in sorted(sub["year"].unique()):
            sel = sub[sub.year == y]
            try:
                dft, _ = load_ltf(tf=("5m" if prof == "tf7" else "30m"),
                                  since=f"{int(y)}-01-01", until=f"{int(y)}-12-31", symbol=sym)
            except Exception as e:
                print(f"  load fail {sym} {prof} {y}: {e!r}", flush=True); continue
            dft.index = pd.DatetimeIndex(dft.index)
            htf = pd.DataFrame({
                "high": dft["high"].resample(rule, label="left", closed="left").max(),
                "low": dft["low"].resample(rule, label="left", closed="left").min(),
                "close": dft["close"].resample(rule, label="left", closed="left").last(),
            }).dropna()
            htf_atr = compute_atr14(htf)
            rule_td = pd.Timedelta(rule)
            close_arr = dft["close"].to_numpy(float)
            low_arr = dft["low"].to_numpy(float); high_arr = dft["high"].to_numpy(float)
            ts_arr = dft.index.to_numpy()
            closed_end = (htf.index + rule_td).to_numpy()
            res = []
            for r_i, row in sel.sort_values("decision_at").iterrows():
                fts = row.decision_at
                n_closed = int(np.searchsorted(closed_end, np.datetime64(fts), "right"))
                if n_closed < 3:
                    res.append((r_i, np.nan, np.nan)); continue
                hc = htf.iloc[:n_closed]
                piv = zigzag(hc, htf_atr.iloc[:n_closed], 1.5)
                if len(piv) < 2:
                    res.append((r_i, np.nan, np.nan)); continue
                pB, pA = piv[-1], piv[-2]
                leg = abs(pB[2] - pA[2])
                i0 = int(np.searchsorted(ts_arr, np.datetime64(pB[0] + rule_td), "left"))
                i1 = int(np.searchsorted(ts_arr, np.datetime64(fts), "right"))
                if leg <= 0 or i1 - i0 < 1:
                    res.append((r_i, np.nan, np.nan)); continue
                if pB[3] == "up":
                    frac = (pB[2] - float(low_arr[i0:i1].min())) / leg
                else:
                    frac = (float(high_arr[i0:i1].max()) - pB[2]) / leg
                res.append((r_i, frac, 1.0 if pB[3] == "up" else -1.0))
            for r_i, frac, ld in res:
                old.at[r_i, "my_frac"] = frac
                old.at[r_i, "my_dir"] = ld
            print(f"  [{sym} {prof} {int(y)}] ok", flush=True)

    d = old[old.my_frac.notna() & old.zz_frac.notna()]
    print(f"\nстрок со сравнением: {len(d)}")
    print(f"corr(rank) мой/старый frac: {np.corrcoef(d.my_frac.rank(), d.zz_frac.rank())[0,1]:.4f}")
    print(f"медиана |разница|: {(d.my_frac - d.zz_frac).abs().median():.4f}")
    print(f"доля совпавших до 1e-4: {100*((d.my_frac - d.zz_frac).abs() < 1e-4).mean():.1f}%")
    print(f"доля совпавших до 0.02: {100*((d.my_frac - d.zz_frac).abs() < 0.02).mean():.1f}%")
    mg = d["dir"].map({"LONG": 1.0, "SHORT": -1.0})
    print(f"same мой vs старый: {100*((mg == d.my_dir) == (mg == d.zz_last_dir)).mean():.1f}% совпало")
    for thr in (0.236, 0.25):
        print(f"  мой <{thr}: {int((d.my_frac < thr).sum())} | старый <{thr}: {int((d.zz_frac < thr).sum())}")
    print("\nDONE")


if __name__ == "__main__":
    main()
