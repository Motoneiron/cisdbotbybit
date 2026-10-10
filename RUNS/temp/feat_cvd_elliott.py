"""CVD + Эллиотт-фичи на ЧЕСТНОМ якоре, для скрина по асимметрии хода.

Якорь решения = момент постановки лимитки живым ботом: ceil_5m(cbt + 30м).
Всё считается только по данным, ЗАКРЫТЫМ до этого момента.

Отличия от прежних версий (важно):
  * Эллиотт: пивот на 8H-баре считается известным на ЗАКРЫТИИ бара (open + 8ч),
    а не на его открытии. Старый `_elliott_proxy_v1.py` брал open ⇒ лукахэд до 8ч.
  * Глубина отката (frac) измеряется по закрытым 30m-барам до якоря, а не по
    8H-барам, часть которых на момент решения ещё формировалась.
  * CVD: минутный бар доступен только с ts_ms + 60с ⇒ окна режутся по (якорь − 1м).
  * of_trig убран: он суммировал дельту ВПЕРЁД от триггера.

Фичи:
  of_30m/1h/4h  — дельта/объём за окно до якоря, со знаком сделки (>0 = поток в нашу сторону)
  act           —活 активность: сделок/мин за 30м против сделок/мин за 12ч
  zz_last_dir   — направление последнего подтверждённого лега (+1 up / −1 down)
  zz_frac       — глубина текущего отката в долях лега
  zz_same_leg   — лег совпадает с направлением сделки
  zz_with       — same_leg и 0.236 <= frac <= 0.786 («откат волны 2/4»)
  zz_chase      — same_leg и frac < 0.236 («гонка»)
  zz_break      — frac > 1 (пробой лега)
  zz_trend      — согласованность последних 4 пивотов
  zz_leg_atr    — длина лега в ATR

Выход: RUNS/temp/feat_cvd_el/<SYM>.pkl
Запуск: python feat_cvd_elliott.py [workers=3]
"""
from __future__ import annotations

import bisect
import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
OUTDIR = f"{BASE}/feat_cvd_el"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
THETA = 1.5
HTF_RULE, HTF_MIN = "8h", 480


def zigzag(htf: pd.DataFrame, atr: pd.Series, theta: float):
    """Пивоты ZigZag. Возвращает (confirm_bar_open, extreme_time, price, kind)."""
    pivots = []
    idx = htf.index
    h, l, c = (htf[k].to_numpy(float) for k in ("high", "low", "close"))
    a = atr.to_numpy(float)
    n = len(htf)
    if n < 3:
        return pivots
    dirn = 1 if c[1] >= c[0] else -1
    ext, ext_i = (h[1] if dirn == 1 else l[1]), 1
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
    return pivots


def one(sym: str) -> str:
    dst = f"{OUTDIR}/{sym}.pkl"
    if os.path.exists(dst):
        return f"skip {sym}"
    t0 = time.time()
    from _cvd_load import load_cvd_minute
    from backtest.data import load_ltf
    from backtest.sweep_atr_filter import compute_atr14

    trades = []
    for f in glob.glob(f"{BASE}/tp_grid/{sym}_*.pkl"):
        for r in pickle.load(open(f, "rb")):
            if r.get("hold") == 6:
                trades.append(r)
    if not trades:
        return f"empty {sym}"

    try:
        m = load_cvd_minute(sym)
    except Exception as e:
        return f"CVD FAIL {sym}: {e!r}"
    mt = m.ts_ms.to_numpy(np.int64)
    c_dlt = np.concatenate([[0.0], np.cumsum(m.delta.to_numpy(float))])
    c_vol = np.concatenate([[0.0], np.cumsum((m.buy + m.sell).to_numpy(float))])
    c_n = np.concatenate([[0.0], np.cumsum(m.n.to_numpy(float))])

    def wsum(cum, t_from_ms: int, t_to_ms: int) -> float:
        i0 = int(np.searchsorted(mt, t_from_ms, "left"))
        i1 = int(np.searchsorted(mt, t_to_ms, "left"))
        return float(cum[i1] - cum[i0])

    rows = []
    years = sorted({int(t["year"]) for t in trades})
    for year in years:
        yt = [t for t in trades if int(t["year"]) == year]
        try:
            d30, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        except Exception:
            continue
        d30.index = pd.DatetimeIndex(d30.index)
        htf = pd.DataFrame({
            "high": d30["high"].resample(HTF_RULE, label="left", closed="left").max(),
            "low": d30["low"].resample(HTF_RULE, label="left", closed="left").min(),
            "close": d30["close"].resample(HTF_RULE, label="left", closed="left").last(),
        }).dropna()
        if len(htf) < 20:
            continue
        atr = compute_atr14(htf)
        pivots = zigzag(htf, atr, THETA)
        # пивот известен только после ЗАКРЫТИЯ бара подтверждения
        known_at = [pd.Timestamp(p[0]) + pd.Timedelta(minutes=HTF_MIN) for p in pivots]
        i30 = pd.DatetimeIndex(d30.index)
        close30 = i30 + pd.Timedelta(minutes=30)
        hi30 = d30["high"].to_numpy(float)
        lo30 = d30["low"].to_numpy(float)

        for t in yt:
            cbt = pd.Timestamp(t["cbt"])
            anchor = (cbt + pd.Timedelta(minutes=30)).ceil("5min")
            sgn = -1.0 if t["dir"] == "SHORT" else 1.0
            a_ms = int(anchor.value // 1_000_000)
            cut = a_ms - 60_000               # последняя ЗАКРЫТАЯ минута
            row = {"hash": t["hash"], "sym": sym, "year": year}
            for lbl, mins in (("of_30m", 30), ("of_1h", 60), ("of_4h", 240),
                              ("of_8h", 480), ("of_12h", 720), ("of_24h", 1440),
                              ("of_72h", 4320)):
                v = wsum(c_vol, cut - mins * 60_000, cut)
                dl = wsum(c_dlt, cut - mins * 60_000, cut)
                row[lbl] = sgn * dl / v if v > 0 else np.nan
            n30 = wsum(c_n, cut - 30 * 60_000, cut)
            n12 = wsum(c_n, cut - 12 * 3600_000, cut)
            row["act"] = (n30 / 30.0) / (n12 / 720.0) if n12 > 0 else np.nan
            # --- Эллиотт ---
            k = bisect.bisect_right(known_at, anchor)
            if k >= 2:
                pB, pA = pivots[k - 1], pivots[k - 2]
                leg = abs(float(pB[2]) - float(pA[2]))
                same = (pB[3] == "up") == (t["dir"] == "LONG")
                frac = np.nan
                if leg > 0:
                    j0 = int(close30.searchsorted(pd.Timestamp(pB[0]) + pd.Timedelta(minutes=HTF_MIN), "left"))
                    j1 = int(close30.searchsorted(anchor, "right"))
                    if j1 > j0:
                        if pB[3] == "up":
                            frac = (float(pB[2]) - float(lo30[j0:j1].min())) / leg
                        else:
                            frac = (float(hi30[j0:j1].max()) - float(pB[2])) / leg
                    else:
                        frac = 0.0
                row["zz_last_dir"] = 1 if pB[3] == "up" else -1
                row["zz_frac"] = frac
                row["zz_same_leg"] = bool(same)
                row["zz_with"] = bool(same and np.isfinite(frac) and 0.236 <= frac <= 0.786)
                row["zz_chase"] = bool(same and np.isfinite(frac) and frac < 0.236)
                row["zz_break"] = bool(np.isfinite(frac) and frac > 1.0)
                av = float(atr.loc[pB[0]]) if pB[0] in atr.index and np.isfinite(atr.loc[pB[0]]) else np.nan
                row["zz_leg_atr"] = leg / av if av and np.isfinite(av) and av > 0 else np.nan
                if k >= 4:
                    ups = [float(pivots[j][2]) for j in range(k - 4, k) if pivots[j][3] == "up"]
                    dns = [float(pivots[j][2]) for j in range(k - 4, k) if pivots[j][3] == "down"]
                    if len(ups) == 2 and len(dns) == 2:
                        if ups[1] > ups[0] and dns[1] > dns[0]:
                            row["zz_trend"] = 1
                        elif ups[1] < ups[0] and dns[1] < dns[0]:
                            row["zz_trend"] = -1
                        else:
                            row["zz_trend"] = 0
            rows.append(row)
    pickle.dump(rows, open(dst + ".tmp", "wb"))
    os.replace(dst + ".tmp", dst)
    return f"OK {sym}: {len(rows)} строк sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nworkers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    os.makedirs(OUTDIR, exist_ok=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nworkers) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, PAIRS), 1):
            print(f"[{i}/{len(PAIRS)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)
