"""Канон «как лайв»: все MARKET-сигналы (fib) торгуются как LIMIT (entry_policy=bot_fib_mkt_limit).

Отличие от tf7_ablations (ABL_MSS_MAIN) — ТОЛЬКО:
  entry_policy="bot_fib_mkt_limit"  → was_fib_mkt (kind=MARKET или fib_stretch_market): kind="LIMIT"
  entry_kind_mode="all"             → не резать по kind (MARKET-ов после конверсии не остаётся)

Остальное как в ABL_MSS_MAIN: профиль tf7_main (5m→4H main-mss, филл 1m), AVD,
limit_bars=2 (10 мин), pos_bars=144 (12ч), TP=1R (патч), fee_model=mexc, max_positions=5.

Запуск: python tf7_canon_live.py [workers]
"""
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_canon_live"
PAIRS = ["DOGE", "KAS", "ADA", "LINK", "LTC", "SOL"]
YEARS = {
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}
CFG = "ABL_MSS_LIVE"

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


def one(task):
    sym, year = task
    dst = f"{OUT}/{CFG}_{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    ba._try_accept_signal = _ORIG_TRY
    _patch_tp1r()
    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest
    try:
        res = run_bot_aligned_backtest(
            since=since, until=until, profile="tf7_main", symbol=sym,
            limit_bars=2, pos_bars=144, htf_ratio=None,
            detect_filters=AVD, fee_model="mexc", max_positions=5,
            entry_policy="bot_fib_mkt_limit",
            entry_kind_mode="all", market_fill_mode="signal_ref",
            cancel_fib2=False, save=False, quiet=True,
            hooks={"on_close": _stamp},
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        r = {"config": CFG, "sym": sym, "year": year}
        for k in ("outcome", "direction", "entry_kind", "entry_px", "stop", "tp", "sp",
                  "hash", "created_bar", "entry_bar", "exit_bar", "htf_time",
                  "entry_ts", "exit_ts", "created_ts"):
            r[k] = t.get(k)
        r["r_net_mexc"] = float(t.get("r_net"))
        rows.append(r)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(rows, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: {len(rows)} сделок sec={time.time()-t0:.0f}"


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
