"""TP-сетка на ЧЕСТНОЙ базе (якорь cbt+30, окно входа 30м, удержание 6/12/24ч).

Главный вопрос: TP=1R при комиссиях Bybit требует WR>=55%, а факт 52%.
Если поднять TP, порог безубыточности падает (1.5R -> ~43%, 2R -> ~35%),
но и WR падает. Где оптимум — считаем один раз и на весь сэмпл.

Для каждого сетапа из filters_off_full_aligned/<PAIR>_tf8_<year>.pkl:
  * вход: первый 1m-бар после cbt+30 (ceil 5m), окно 30 мин, как у живого бота;
  * путь по 1m: MFE/MAE в R, и для сетки TP -> исход (tp/sl/time) с комиссиями;
  * варианты: TP in {1, 1.25, 1.5, 2, 3}, hold in {6, 12, 24}ч,
    плюс BE (перевод стопа в безубыток после +0.5R / +1R).

Пишет RUNS/temp/tp_grid/<PAIR>_<year>.pkl (по одному на пару-год, резюмируемо).
Запуск: python sim_tp_grid_honest.py [workers=5]
"""
import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

MAKER, TAKER = 0.00036, 0.0010
MIN_STOP = 0.0025
WIN = 30                      # окно поиска входа, мин
HOLDS = [6, 12, 24]           # часы удержания
TPS = [1.0, 1.25, 1.5, 2.0, 3.0]
BE_TRIGGERS = [0.5, 1.0]      # перевод стопа в БУ после +Х R
TRAILS = [0.5, 1.0]           # трейлинг-стоп на Х R позади максимума
SRC = "D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned"
OUTDIR = "D:/PYTHON/cisdbotbybit/RUNS/temp/tp_grid"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def path_outcomes(hi, lo, cl, j, entry, stop, long, n_bars):
    """Исходы по 1m-пути с момента налива j: сетка TP x hold + BE-варианты."""
    risk = abs(entry - stop)
    ks = slice(j, min(len(hi), j + n_bars + 1))
    kh, kl, kc = hi[ks], lo[ks], cl[ks]
    if len(kh) == 0:
        return None
    # excursion в R на каждом баре
    if long:
        fav = (kh - entry) / risk
        adv = (entry - kl) / risk
    else:
        fav = (entry - kl) / risk
        adv = (kh - entry) / risk
    i_sl_arr = np.where(adv >= 1.0)[0]
    i_sl = int(i_sl_arr[0]) if len(i_sl_arr) else 10 ** 9
    res = {"mfe_r": float(fav.max()), "mae_r": float(adv.max())}
    # MFE до момента стопа (важно для BE/трейла)
    cut = i_sl if i_sl != 10 ** 9 else len(fav) - 1
    res["mfe_before_sl"] = float(fav[: cut + 1].max())
    for tp_m in TPS:
        i_tp_arr = np.where(fav >= tp_m)[0]
        i_tp = int(i_tp_arr[0]) if len(i_tp_arr) else 10 ** 9
        if i_tp <= i_sl and i_tp != 10 ** 9:
            res[f"out_{tp_m}"], res[f"r_{tp_m}"] = "tp", tp_m
        elif i_sl != 10 ** 9:
            res[f"out_{tp_m}"], res[f"r_{tp_m}"] = "sl", -1.0
        else:
            px = float(kc[-1])
            r = (px - entry) / risk if long else (entry - px) / risk
            res[f"out_{tp_m}"], res[f"r_{tp_m}"] = "time", r
    i_tp1_arr = np.where(fav >= 1.0)[0]
    i_tp1 = int(i_tp1_arr[0]) if len(i_tp1_arr) else 10 ** 9
    # BE: после +X R стоп переносится в безубыток. Важно: после переноса позицию
    # закрывает ВОЗВРАТ К ВХОДУ (adv >= 0), а не исходный стоп, поэтому TP
    # засчитывается только если он раньше этого возврата.
    for be in BE_TRIGGERS:
        i_be_arr = np.where(fav >= be)[0]
        i_be = int(i_be_arr[0]) if len(i_be_arr) else 10 ** 9
        if i_be == 10 ** 9 or i_sl < i_be:
            # БУ не встал: обычная механика TP1R / стоп / таймаут
            if i_tp1 <= i_sl and i_tp1 != 10 ** 9:
                out, r = "tp", 1.0
            elif i_sl != 10 ** 9:
                out, r = "sl", -1.0
            else:
                px = float(kc[-1])
                out = "time"
                r = (px - entry) / risk if long else (entry - px) / risk
        else:
            back_arr = np.where(adv[i_be + 1:] >= 0.0)[0]
            i_bex = i_be + 1 + int(back_arr[0]) if len(back_arr) else 10 ** 9
            if i_tp1 < i_bex:
                out, r = "tp", 1.0
            elif i_bex != 10 ** 9:
                out, r = "be", 0.0
            else:
                px = float(kc[-1])
                out = "time"
                r = (px - entry) / risk if long else (entry - px) / risk
        res[f"be{be}_out"], res[f"be{be}_r"] = out, r
    # TRAIL: стоп тянется на trail R позади достигнутого максимума (без фикс. TP)
    for trail in TRAILS:
        run = np.maximum.accumulate(fav)
        armed = run >= trail
        stop_lvl = np.where(armed, run - trail, -1.0)
        hit = np.where(adv >= -np.concatenate(([stop_lvl[0]], stop_lvl[:-1])))[0]
        i_x = int(hit[0]) if len(hit) else 10 ** 9
        if i_x != 10 ** 9:
            lvl = stop_lvl[i_x - 1] if i_x > 0 else -1.0
            res[f"tr{trail}_out"], res[f"tr{trail}_r"] = ("trail" if lvl > -1.0 else "sl"), float(lvl)
        else:
            px = float(kc[-1])
            r = (px - entry) / risk if long else (entry - px) / risk
            res[f"tr{trail}_out"], res[f"tr{trail}_r"] = "time", r
    return res


def one(task):
    sym, year = task
    dst = f"{OUTDIR}/{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    src = sorted(glob.glob(f"{SRC}/{sym}_tf8_{year}*.pkl"))
    if not src:
        return f"nosrc {sym} {year}"
    t0 = time.time()
    from backtest.data import load_ltf
    c = pickle.load(open(src[0], "rb"))
    sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
    trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    if not trades:
        return f"empty {sym} {year}"
    try:
        df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    except Exception as e:
        return f"DATA FAIL {sym} {year}: {e!r}"
    ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
    hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    step = max(1, int(round(np.median(np.diff(ts)))))
    rows = []
    for t in trades:
        s = sigs.get(str(t.get("hash")))
        if not s:
            continue
        entry, stop = float(t.get("entry_px") or 0), float(t.get("stop") or 0)
        if entry <= 0 or stop <= 0:
            continue
        sp = abs(entry - stop) / entry
        if sp < MIN_STOP:
            continue
        long = t.get("direction") == "LONG"
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        from_ts = (cbt + pd.Timedelta(minutes=30)).ceil("5min")
        t0m = int(from_ts.value // 60_000_000_000)
        i0 = int(np.searchsorted(ts, t0m, side="left"))
        if i0 >= len(ts):
            continue
        seg = slice(i0, min(len(ts), i0 + int(WIN / step) + 1))
        hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
        if len(hit) == 0:
            continue
        j = i0 + int(hit[0])
        base = {"sym": sym, "year": year, "dir": t.get("direction"), "hash": str(t.get("hash")),
                "cbt": cbt, "entry": entry, "stop": stop, "stop_pct": sp * 100,
                "fee_maker2": 2 * MAKER / sp, "fee_mix": (MAKER + TAKER) / sp}
        for hold in HOLDS:
            r = path_outcomes(hi, lo, cl, j, entry, stop, long, int(hold * 60 / step))
            if r is None:
                continue
            rows.append({**base, "hold": hold, **r})
    pickle.dump(rows, open(dst + ".tmp", "wb"))
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: {len(rows)} строк ({len(trades)} сетапов) sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nworkers = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    os.makedirs(OUTDIR, exist_ok=True)
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    skip = {("KAS", y) for y in (2020, 2021, 2022)}
    tasks = [(s, y) for s in PAIRS for y in years if (s, y) not in skip]
    print(f"tasks: {len(tasks)} | workers: {nworkers}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nworkers) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)
