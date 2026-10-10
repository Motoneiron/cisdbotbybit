"""Абляции tf7-стека (C5-модель: LIMIT-only, TP=1R) + сбор времён для портфеля.

Конфиги (единый пул 10 пар, честный якорь, патчи сброшены перед задачей):
  BASE_rerun   — база as-is: A+V+D, MSS 1m, окно 10м, поз 12ч, старший 4H.
                 Полные трейды + entry_ts/exit_ts/created_ts (on_close hook).
  ABL_FILT_OFF — детект без фильтров A+V+D.
  ABL_MSS_MAIN — MSS на main (5m) вместо 1m; филл по-прежнему 1m.
  ABL_LIM30    — окно лимитки 30 мин (limit_bars=6).
  ABL_POS6H    — удержание 6 ч (pos_bars=72).
  ABL_HTF8H    — старший 8H (htf_ratio=480).

Запуск: python tf7_ablations.py [workers=12]
"""
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_abl"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
YEARS = {
    2020: ("2020-09-14", "2020-12-31"),
    2021: ("2021-01-01", "2021-12-31"),
    2022: ("2022-01-01", "2022-12-31"),
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
KAS_SKIP = {2020, 2021, 2022}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}
FILT_OFF = {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}
CONFIGS = ("BASE_rerun", "ABL_FILT_OFF", "ABL_MSS_MAIN", "ABL_LIM30", "ABL_POS6H", "ABL_HTF8H")

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_tf7_main = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7_main["fill_timeframe"] = "1m"
_tf7_main["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _tf7_main

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_FILL = ba._fill_from_after_confirm_close
_ORIG_TRY = ba._try_accept_signal


def _reset_patches():
    ba._fill_from_after_confirm_close = _ORIG_FILL
    ba._try_accept_signal = _ORIG_TRY


def _patch_tp1r():
    orig = ba._try_accept_signal
    def patched(sim, sig, tf, bar_i, *a, **kw):
        try:
            e, s = float(sig["entry"]), float(sig["stop"])
            if e > 0 and s > 0 and e != s:
                sig = {**sig, "tp": 2.0 * e - s}
        except Exception:
            pass
        return orig(sim, sig, tf, bar_i, *a, **kw)
    ba._try_accept_signal = patched


def _stamp(trade, df=None, sim=None):
    """on_close hook: записать таймстампы баров в трейд."""
    try:
        if df is not None:
            for k, ik in (("created_ts", "created_bar"), ("entry_ts", "entry_bar"), ("exit_ts", "exit_bar")):
                ib = trade.get(ik)
                if ib is not None:
                    trade[k] = str(df.index[int(ib)])
    except Exception:
        pass


def one(task):
    cfg_name, sym, year = task
    dst = f"{OUT}/{cfg_name}_{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {cfg_name} {sym} {year}"
    _reset_patches()
    _patch_tp1r()
    since, until = YEARS[year]
    prof = "tf7_main" if cfg_name == "ABL_MSS_MAIN" else "tf7"
    limit_bars, pos_bars, htf = 2, 144, None
    if cfg_name == "ABL_LIM30":
        limit_bars = 6
    if cfg_name == "ABL_POS6H":
        pos_bars = 72
    if cfg_name == "ABL_HTF8H":
        htf = 480
    fil = FILT_OFF if cfg_name == "ABL_FILT_OFF" else AVD
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest
    try:
        res = run_bot_aligned_backtest(
            since=since, until=until, profile=prof, symbol=sym,
            limit_bars=limit_bars, pos_bars=pos_bars, htf_ratio=htf,
            detect_filters=fil, fee_model="mexc", max_positions=5,
            entry_kind_mode="limit_only", market_fill_mode="signal_ref",
            cancel_fib2=False, save=False, quiet=True,
            hooks={"on_close": _stamp},
        )
    except Exception as e:
        return f"FAIL {cfg_name} {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        r = {"config": cfg_name, "sym": sym, "year": year}
        for k in ("outcome", "direction", "entry_kind", "entry_px", "stop", "tp", "sp",
                  "hash", "created_bar", "entry_bar", "exit_bar", "htf_time",
                  "entry_ts", "exit_ts", "created_ts"):
            r[k] = t.get(k)
        r["r_net_mexc"] = float(t.get("r_net"))
        rows.append(r)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(rows, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {cfg_name} {sym} {year}: {len(rows)} сделок sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    only = None
    nw = 12
    for a in sys.argv[1:]:
        if ":" in a:
            only = a
        else:
            nw = int(a)
    os.makedirs(OUT, exist_ok=True)
    if only:
        c, s, y = only.split(":")
        tasks = [(c, s.upper(), int(y))]
    else:
        tasks = []
        for c in CONFIGS:
            for s in PAIRS:
                for y in YEARS:
                    if s == "KAS" and y in KAS_SKIP:
                        continue
                    tasks.append((c, s, y))
    print(f"задач: {len(tasks)} | воркеров: {nw}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE {time.time()-t0:.0f}s", flush=True)
