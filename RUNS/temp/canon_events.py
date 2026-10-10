"""canon_events.py — канон ABL_MSS_MAIN (limit_only), но со структурным логом:

  signals   — все сигналы, выданные детектом на каждом канонном скане
  decisions — решения приёма (_try_accept_signal): accepted/rejected (по hash)
  trades    — исполненные сделки (как tf7_ablations)

Цель: классификация живых сделок 2024 по 6 парам (paired / notseen / reject_market / ...)
для задачи B — вычленения признаков плохих сделок.

Запуск: python canon_events.py [workers]
"""
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/canon_events"
PAIRS = ["DOGE", "KAS", "ADA", "LINK", "LTC", "SOL"]
YEARS = {
    2024: ("2024-01-01", "2024-12-31"),
}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_tf7_main = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7_main["fill_timeframe"] = "1m"
_tf7_main["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _tf7_main

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_TRY = ba._try_accept_signal


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
    try:
        if df is not None:
            for k, ik in (("created_ts", "created_bar"), ("entry_ts", "entry_bar"), ("exit_ts", "exit_bar")):
                ib = trade.get(ik)
                if ib is not None:
                    trade[k] = str(df.index[int(ib)])
    except Exception:
        pass


def _sig_row(s, scan_ts):
    def g(k, d=None):
        v = s.get(k)
        return v if v is not None else d
    try:
        e = float(g("entry") or 0); st = float(g("stop") or 0)
        sp = abs(e - st) / e if e else None
    except Exception:
        sp = None
    return {
        "scan": scan_ts,
        "hash": str(g("hash") or ""),
        "direction": str(g("direction") or ""),
        "cbt": str(g("confirm_bar_time") or "")[:19],
        "swc": str(g("sweep_close_bar_time") or "")[:19],
        "trig": str(g("trigger_bar_time") or "")[:19],
        "htf": str(g("htf_time") or "")[:19],
        "entry": g("entry"), "stop": g("stop"), "tp": g("tp"),
        "sp": sp,
        "fib": bool(g("fib_stretch_market", False)),
        "late": bool(g("late_retest", False)),
        "obc": bool(g("one_bar_sweep_cisd", False)),
        "cos": bool(g("confirm_on_sweep", False)),
        "touches": g("prior_touches"),
        "qual": g("quality_score"),
        "cisd": g("cisd_level"),
        "sweep_lvl": g("htf_sweep_level") or g("sweep_level"),
        "trig_ext": g("trigger_extreme"),
    }


def one(task):
    sym, year = task
    dst = f"{OUT}/{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    ba._try_accept_signal = _ORIG_TRY
    _patch_tp1r()

    import cisdbot as _bot

    signals_log = []
    decisions = []

    _det_orig = _bot.detect_signals

    def det_wrap(df_win, seen, *a, **kw):
        out = _det_orig(df_win, seen, *a, **kw) or []
        try:
            scan_ts = str(df_win.index[-1])[:19]
            for s in out:
                signals_log.append(_sig_row(s, scan_ts))
        except Exception:
            pass
        return out

    _try_wrapped = ba._try_accept_signal

    def try_wrap(sim, sig, tf, bar_i, *a, **kw):
        out = _try_wrapped(sim, sig, tf, bar_i, *a, **kw)
        try:
            decisions.append({
                "hash": str(sig.get("hash") or ""),
                "accepted": out is not None,
                "direction": str(sig.get("direction") or ""),
                "cbt": str(sig.get("confirm_bar_time") or "")[:19],
                "fib": bool(sig.get("fib_stretch_market")),
            })
        except Exception:
            pass
        return out

    _bot.detect_signals = det_wrap
    ba._try_accept_signal = try_wrap

    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest
    try:
        res = run_bot_aligned_backtest(
            since=since, until=until, profile="tf7_main", symbol=sym,
            limit_bars=2, pos_bars=144, htf_ratio=None,
            detect_filters=AVD, fee_model="mexc", max_positions=5,
            entry_kind_mode="limit_only", market_fill_mode="signal_ref",
            cancel_fib2=False, save=False, quiet=True,
            hooks={"on_close": _stamp},
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    finally:
        _bot.detect_signals = _det_orig
        ba._try_accept_signal = _ORIG_TRY

    trades = []
    for t in res.get("trades") or []:
        r = {}
        for k in ("outcome", "direction", "entry_kind", "entry_px", "stop", "tp", "sp",
                  "hash", "created_bar", "entry_bar", "exit_bar", "htf_time",
                  "entry_ts", "exit_ts", "created_ts"):
            r[k] = t.get(k)
        r["r_net_mexc"] = float(t.get("r_net"))
        trades.append(r)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump({"signals": signals_log, "decisions": decisions, "trades": trades}, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: sig={len(signals_log)} dec={len(decisions)} trades={len(trades)} sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    only = sys.argv[2] if len(sys.argv) > 2 else None
    os.makedirs(OUT, exist_ok=True)
    if only:
        s, y = only.split(":")
        tasks = [(s.upper(), int(y))]
    else:
        tasks = [(s, y) for s in PAIRS for y in YEARS]
    print(f"задач: {len(tasks)} | воркеров: {nw}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE {time.time()-t0:.0f}s", flush=True)
