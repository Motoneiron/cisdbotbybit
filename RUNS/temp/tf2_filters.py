"""Фильтры на tf2-потоке (1H->Daily): vwap / EMA3-1H slope / D+W свеча.

Пост-фактум и КАУЗАЛЬНО на 7033 сделках (tp_grid_other, hold 24, TP1R).
- vwap: дневной кумулятив (typical price, UTC-reset) по 5m; vd = (entry-vwap)/vwap;
  гейт как в боте: LONG vd>=0, SHORT vd<=0; нет данных -> fail-open.
- slope: EMA3 на 1H close (span=3), slope_pct = (ema3/ema3.shift-1)*100; на последнем
  ЗАКРЫТОМ 1H-баре до якоря (cbt+60m); порог 0.02% (боковик разрешён обеим).
- D/W: цвет текущей недельной/дневной свечи на момент входа (open vs close до t_j).
Момент входа t_j восстановлен из 1m (первое касание лимита в окне 24ч).

Выход: RUNS/temp/tf2_filters/<SYM>_<year>.pkl + сводка в stdout.
"""
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "D:/PYTHON")
sys.path.insert(0, "D:/PYTHON/CISDBOT")

TPD = "D:/PYTHON/cisdbotbybit/RUNS/temp"
OUTDIR = f"{TPD}/tf2_filters"
SLOPE_TH = 0.02
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def one(task):
    sym, year = task
    dst = f"{OUTDIR}/{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    src = f"{TPD}/tp_grid_other/{sym}_tf2_{year}.pkl"
    if not os.path.exists(src):
        return f"nosrc {sym} {year}"
    rows = [r for r in pickle.load(open(src, "rb")) if r["hold"] == 24]
    if not rows:
        return f"empty {sym} {year}"
    t0 = time.time()
    from backtest.data import load_ltf
    try:
        d5, _ = load_ltf(tf="5m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        d1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    except Exception as e:  # noqa: BLE001
        return f"DATA FAIL {sym} {year}: {e!r}"
    d5 = d5.sort_index()
    d5 = d5[~d5.index.duplicated(keep="last")]
    d1 = d1.sort_index()
    d1 = d1[~d1.index.duplicated(keep="last")]
    ts1 = pd.DatetimeIndex(d1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
    ts1n = pd.DatetimeIndex(d1.index)
    hi1 = d1["high"].to_numpy(dtype=float)
    lo1 = d1["low"].to_numpy(dtype=float)

    # VWAP (5m, UTC day reset)
    typical = (d5["high"] + d5["low"] + d5["close"]) / 3.0
    day = d5.index.floor("D")
    vwap = (typical * d5["volume"]).groupby(day).cumsum() / d5["volume"].groupby(day).cumsum()
    vts = d5.index
    vvw = vwap.to_numpy(dtype=float)

    # slope EMA3 1H
    c1h = d5["close"].resample("1h").last().dropna()
    ema3 = c1h.ewm(span=3, adjust=False).mean()
    slope = ((ema3 - ema3.shift(1)) / ema3.shift(1) * 100.0).dropna()
    s_idx = slope.index
    s_val = slope.to_numpy(dtype=float)

    # D / W текущие
    o_w = d5["open"].resample("W-MON", label="left", closed="left").first()
    o_d = d5["open"].resample("D", label="left", closed="left").first()
    cl5 = d5["close"].to_numpy(dtype=float)
    c5_idx = d5.index

    out = []
    for r in rows:
        cbt = pd.Timestamp(r["cbt"])
        entry = float(r["entry"])
        long = r["dir"] == "LONG"
        from_ts = (cbt + pd.Timedelta(minutes=60)).ceil("5min")
        t0m = int(from_ts.value // 60_000_000_000)
        i0 = int(np.searchsorted(ts1, t0m, side="left"))
        seg = slice(i0, min(len(ts1), i0 + 24 * 60 + 1))
        hit = np.where(lo1[seg] <= entry)[0] if long else np.where(hi1[seg] >= entry)[0]
        t_j = ts1n[i0 + int(hit[0])] if len(hit) else None
        tq = t_j if t_j is not None else from_ts

        # vwap
        k = int(vts.searchsorted(tq, side="right")) - 1
        vw = vvw[k] if k >= 0 else np.nan
        vd = (entry - vw) / vw if vw and not np.isnan(vw) else np.nan
        vwap_ok = True
        if not np.isnan(vd):
            vwap_ok = (vd >= 0) if long else (vd <= 0)

        # slope: последний 1H-бар, закрывшийся до from_ts
        k2 = int(s_idx.searchsorted(from_ts - pd.Timedelta(hours=1), side="right")) - 1
        sp = s_val[k2] if k2 >= 0 else np.nan
        slope_ok = True
        if not np.isnan(sp):
            slope_ok = not ((long and sp < -SLOPE_TH) or ((not long) and sp > SLOPE_TH))

        # D/W цвет на tq
        k3 = int(c5_idx.searchsorted(tq, side="right")) - 1
        close_now = cl5[k3] if k3 >= 0 else np.nan
        dcd = np.nan
        wcd = np.nan
        p = int(o_d.index.searchsorted(tq, side="right")) - 1
        if p >= 0:
            dcd = close_now > o_d.iloc[p]
        p = int(o_w.index.searchsorted(tq, side="right")) - 1
        if p >= 0:
            wcd = close_now > o_w.iloc[p]

        out.append({**r, "t_j": t_j, "vd": float(vd) if not np.isnan(vd) else None,
                    "vwap_ok": bool(vwap_ok), "slope_pct": float(sp) if not np.isnan(sp) else None,
                    "slope_ok": bool(slope_ok),
                    "d_bull": None if np.isnan(dcd) else bool(dcd),
                    "w_bull": None if np.isnan(wcd) else bool(wcd)})
    pickle.dump(out, open(dst + ".tmp", "wb"))
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: {len(out)} сд sec={time.time() - t0:.0f}"


if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    os.makedirs(OUTDIR, exist_ok=True)
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    skip = {("KAS", y) for y in (2020, 2021, 2022)}
    tasks = [(s, y) for s in PAIRS for y in years if (s, y) not in skip]
    print(f"tasks: {len(tasks)} | workers: {nw}", flush=True)
    from multiprocessing import Pool

    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time() - t0:.0f}s {msg}", flush=True)
    print(f"DONE in {time.time() - t0:.0f}s", flush=True)
