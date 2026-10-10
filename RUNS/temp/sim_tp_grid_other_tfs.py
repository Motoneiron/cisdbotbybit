"""TP-сетка на честной базе для tf0/tf1/tf2 (5m->1H, 15m->4H, 1H->Daily).

Аналог sim_tp_grid_honest.py (tf8), но параметры окон — бот-профильные:
  * вход: первый 1m-бар после close конфирм-бара (cbt + confirm_min).ceil(5m);
  * окно входа: limit_h профиля (tf0: 60м, tf1: 300м, tf2: 1440м);
  * hold: сетка [6, 12, 16, 24] ч (tf0 бот-hold=6, tf1=16, tf2=24);
  * TP 1R (главный интерес), + сетка 1.25/1.5/2/3, BE, трейлы; комиссии Bybit;
  * MIN_STOP 0.25% как в каноне tf8 (в боте 0.5%).

Источник: свежайшие RUNS/*/bot_aligned/<SYM>_<profile>_<year>*.pkl
Выход: RUNS/temp/tp_grid_other/<SYM>_<profile>_<year>.pkl
Запуск: python sim_tp_grid_other_tfs.py [workers=5]
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
HOLDS = [6, 12, 16, 24]
TPS = [1.0, 1.25, 1.5, 2.0, 3.0]
BE_TRIGGERS = [0.5, 1.0]
TRAILS = [0.5, 1.0]
OUTDIR = "D:/PYTHON/cisdbotbybit/RUNS/temp/tp_grid_other"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]

# профиль: (confirm_min для якоря, окно входа мин, бот-hold ч)
PROF = {
    "tf0": {"confirm_min": 5, "win": 60, "hold": 6},
    "tf1": {"confirm_min": 15, "win": 300, "hold": 16},
    "tf2": {"confirm_min": 60, "win": 1440, "hold": 24},
}


def path_outcomes(hi, lo, cl, j, entry, stop, long, n_bars):
    """Исходы по 1m-пути с момента налива j: сетка TP x hold + BE/трейлы."""
    risk = abs(entry - stop)
    ks = slice(j, min(len(hi), j + n_bars + 1))
    kh, kl, kc = hi[ks], lo[ks], cl[ks]
    if len(kh) == 0:
        return None
    if long:
        fav = (kh - entry) / risk
        adv = (entry - kl) / risk
    else:
        fav = (entry - kl) / risk
        adv = (kh - entry) / risk
    i_sl_arr = np.where(adv >= 1.0)[0]
    i_sl = int(i_sl_arr[0]) if len(i_sl_arr) else 10 ** 9
    res = {"mfe_r": float(fav.max()), "mae_r": float(adv.max())}
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
    for be in BE_TRIGGERS:
        i_be_arr = np.where(fav >= be)[0]
        i_be = int(i_be_arr[0]) if len(i_be_arr) else 10 ** 9
        if i_be == 10 ** 9 or i_sl < i_be:
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


def find_src(sym, profile, year):
    pats = glob.glob(f"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{profile}_{year}-*-*.pkl")
    if not pats:
        return None
    return max(pats, key=os.path.getmtime)


def one(task):
    sym, profile, year = task
    dst = f"{OUTDIR}/{sym}_{profile}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {profile} {year}"
    src = find_src(sym, profile, year)
    if not src:
        return f"nosrc {sym} {profile} {year}"
    cfg = PROF[profile]
    t0 = time.time()
    from backtest.data import load_ltf
    c = pickle.load(open(src, "rb"))
    sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
    trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    if not trades:
        return f"empty {sym} {profile} {year}"
    try:
        df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    except Exception as e:  # noqa: BLE001
        return f"DATA FAIL {sym} {profile} {year}: {e!r}"
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
        from_ts = (cbt + pd.Timedelta(minutes=int(cfg["confirm_min"]))).ceil("5min")
        t0m = int(from_ts.value // 60_000_000_000)
        i0 = int(np.searchsorted(ts, t0m, side="left"))
        if i0 >= len(ts):
            continue
        seg = slice(i0, min(len(ts), i0 + int(cfg["win"] / step) + 1))
        hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
        if len(hit) == 0:
            continue
        j = i0 + int(hit[0])
        base = {"sym": sym, "profile": profile, "year": year, "dir": t.get("direction"),
                "hash": str(t.get("hash")), "cbt": cbt, "entry": entry, "stop": stop,
                "stop_pct": sp * 100,
                "fee_maker2": 2 * MAKER / sp, "fee_mix": (MAKER + TAKER) / sp}
        for hold in HOLDS:
            r = path_outcomes(hi, lo, cl, j, entry, stop, long, int(hold * 60 / step))
            if r is None:
                continue
            rows.append({**base, "hold": hold, **r})
    pickle.dump(rows, open(dst + ".tmp", "wb"))
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {profile} {year}: {len(rows)} строк ({len(trades)} сетапов) sec={time.time() - t0:.0f}"


if __name__ == "__main__":
    nworkers = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    os.makedirs(OUTDIR, exist_ok=True)
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    skip = {("KAS", y) for y in (2020, 2021, 2022)}
    tasks = [(s, p, y) for p in PROF for s in PAIRS for y in years if (s, y) not in skip]
    print(f"tasks: {len(tasks)} | workers: {nworkers}", flush=True)
    from multiprocessing import Pool

    t0 = time.time()
    with Pool(nworkers) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time() - t0:.0f}s {msg}", flush=True)
    print(f"DONE in {time.time() - t0:.0f}s", flush=True)
