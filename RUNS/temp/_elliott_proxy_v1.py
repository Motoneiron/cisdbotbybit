"""Эллиотт-прокси v1: структура откатов (ZigZag по HTF) как фичи к потоку.

HTF: tf7→4H (из 5m), tf8→8H (из 30m). ZigZag с ATR-порогом θ (по умолчанию 1.5),
каузально (пивот известен только с бара подтверждения). Фичи на decision_at сделки:
  zz_last_dir  — направление последнего ЗАВЕРШЁННОГО лега (+1 up / −1 down)
  zz_frac      — глубина текущего отката в долях этого лега (может >1 — пробой)
  zz_with      — (last_dir == dir сделки) и 0.236 <= frac <= 0.786  [«откат волны 2/4»]
  zz_break     — frac > 1.0
  zz_trend     — согласованность последних 4 пивотов (+1 up / −1 down / 0 пила)
  zz_leg_atr   — длина лега в ATR на баре пивота
  bars_since_pivot
Использование: python _elliott_proxy_v1.py <stream_v2_pkl> [--tag el] [--theta 1.5]
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

NEW = ["zz_last_dir", "zz_frac", "zz_with", "zz_break", "zz_trend", "zz_leg_atr", "bars_since_pivot"]


def zigzag(htf: pd.DataFrame, atr: pd.Series, theta: float):
    """Возвращает список подтверждённых пивотов и текущее незавершённое состояние.
    Пивот: (confirm_time, extreme_time, price, kind); kind 'up' = максимум (конец up-лега)."""
    pivots = []
    idx = htf.index
    h = htf["high"].to_numpy(float)
    l = htf["low"].to_numpy(float)
    c = htf["close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(htf)
    if n < 3:
        return pivots, None
    dirn = 1 if c[1] >= c[0] else -1
    ext = h[1] if dirn == 1 else l[1]
    ext_i = 1
    for i in range(2, n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if dirn == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif (ext - l[i]) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "up"))
                dirn, ext, ext_i = -1, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif (h[i] - ext) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "down"))
                dirn, ext, ext_i = 1, h[i], i
    return pivots, (dirn, ext, ext_i)


def frac_of(htf, atr_ser, pB_conf, pB_px, pB_kind, decision_ts, leg_len):
    """Глубина отката от pB на баре decision."""
    if leg_len <= 0:
        return None
    sl = htf.loc[(htf.index > pB_conf) & (htf.index <= decision_ts)]
    if sl.empty:
        return 0.0
    if pB_kind == "up":
        ext = float(sl["low"].min())
        return (pB_px - ext) / leg_len
    ext = float(sl["high"].max())
    return (ext - pB_px) / leg_len


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stream")
    ap.add_argument("--tag", default="el")
    ap.add_argument("--theta", type=float, default=1.5)
    args = ap.parse_args()
    df = pd.read_pickle(args.stream)
    for c in NEW:
        df[c] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        rule = "4h" if prof == "tf7" else "8h"
        mmin = 5 if prof == "tf7" else 30
        dft, _ = load_ltf(tf=tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        htf = pd.DataFrame(
            {
                "high": dft["high"].resample(rule, label="left", closed="left").max(),
                "low": dft["low"].resample(rule, label="left", closed="left").min(),
                "close": dft["close"].resample(rule, label="left", closed="left").last(),
            }
        ).dropna()
        atr = compute_atr14(htf)
        pivots, _cur = zigzag(htf, atr, args.theta)
        if not pivots:
            continue
        conf_times = [p[0] for p in pivots]
        for r_i, row in df.loc[idx].iterrows():
            dec = pd.Timestamp(str(row["decision_at"]))
            # пивоты, ПОДТВЕРЖДЁННЫЕ до decision (строго)
            k = bisect.bisect_left(conf_times, dec)
            if k < 1:
                continue
            pB = pivots[k - 1]
            pA = pivots[k - 2] if k >= 2 else None
            if pA is None:
                continue
            leg_len = abs(pB[2] - pA[2])
            frac = frac_of(htf, atr, pB[0], pB[2], pB[3], dec, leg_len)
            df.at[r_i, "zz_last_dir"] = 1 if pB[3] == "up" else -1
            df.at[r_i, "zz_frac"] = frac
            if frac is not None:
                df.at[r_i, "zz_with"] = 1.0 if ((pB[3] == "up") == (row["dir"] == "LONG") and 0.236 <= frac <= 0.786) else 0.0
                df.at[r_i, "zz_break"] = 1.0 if frac > 1.0 else 0.0
            df.at[r_i, "zz_leg_atr"] = leg_len / float(atr.loc[pB[0]]) if pd.notna(atr.loc[pB[0]]) else np.nan
            # тренд по последним 4 пивотам
            if k >= 4:
                ups = [pivots[j][2] for j in range(k - 4, k) if pivots[j][3] == "up"]
                dns = [pivots[j][2] for j in range(k - 4, k) if pivots[j][3] == "down"]
                if len(ups) == 2 and len(dns) == 2:
                    if ups[1] > ups[0] and dns[1] > dns[0]:
                        df.at[r_i, "zz_trend"] = 1
                    elif ups[1] < ups[0] and dns[1] < dns[0]:
                        df.at[r_i, "zz_trend"] = -1
                    else:
                        df.at[r_i, "zz_trend"] = 0
            bs = htf.index[bisect.bisect_right(list(htf.index), pB[0]) - 1]
            df.at[r_i, "bars_since_pivot"] = int((dec - pd.Timestamp(pB[0])) / pd.Timedelta(minutes=mmin))
    out = args.stream.replace(".pkl", f"_{args.tag}.pkl")
    df.to_pickle(out)

    def line(name, part):
        dec = part[part["outcome"].isin(["tp", "sl"])]
        w = 100.0 * (dec["outcome"] == "tp").mean() if len(dec) else 0.0
        print(f"{name:34s} n={len(part):5d} WR={w:5.1f}% ΣR={part['r_net'].sum():8.1f} AvgR={part['r_net'].mean() if len(part) else 0:6.3f}", flush=True)

    print(f"saved: {out} | theta={args.theta}", flush=True)
    s = df[df["zz_frac"].notna()]
    line("ALL (с пивотами)", s)
    print("-- last_dir x dir --", flush=True)
    for ld in (1, -1):
        for d in ("LONG", "SHORT"):
            g = s[(s["zz_last_dir"] == ld) & (s["dir"] == d)]
            if len(g):
                line(f"last={'up' if ld==1 else 'down'} {d}", g)
    print("-- frac-зоны (направление вдоль last_dir) --", flush=True)
    with_ = s[(s["zz_last_dir"] == 1) & (s["dir"] == "LONG") | (s["zz_last_dir"] == -1) & (s["dir"] == "SHORT")]
    for lo, hi in [(0, 0.236), (0.236, 0.5), (0.5, 0.786), (0.786, 1.0), (1.0, 99)]:
        g = with_[(with_["zz_frac"] >= lo) & (with_["zz_frac"] < hi)]
        if len(g):
            line(f"with frac [{lo:.3f},{hi:.3f})", g)
    print("-- против last_dir  --", flush=True)
    against = s[(s["zz_last_dir"] == 1) & (s["dir"] == "SHORT") | (s["zz_last_dir"] == -1) & (s["dir"] == "LONG")]
    line("against ALL", against)
    print("-- zz_with маска --", flush=True)
    line("zz_with=True", s[s["zz_with"] == True])
    line("zz_with=False", s[s["zz_with"] != True])
    print("-- zz_trend --", flush=True)
    for tv in (-1, 0, 1):
        g = s[s["zz_trend"] == tv]
        if len(g):
            line(f"trend={tv}", g)
    print("-- корреляции (анти-алиас чек) --", flush=True)
    for cn in ("vd", "sweep_atr", "quality_score"):
        if cn in s.columns:
            c = s[["zz_frac", cn]].corr().iloc[0, 1]
            print(f"  corr(zz_frac, {cn}) = {c:.3f}", flush=True)


if __name__ == "__main__":
    main()
