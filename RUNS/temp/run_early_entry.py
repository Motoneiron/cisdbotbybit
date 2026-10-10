"""Ранний вход: прогон движка с confirm_timeframe=5m (как живой ДО фикса 16.09).

Движок теперь честный (филл после close конфирм-бара), поэтому:
  * профиль tf8_mss5 = tf8 + confirm_timeframe="5m" → сигналы по 5m-конфирму,
    включая класс «30m-свеча только проткнула уровень фитилём» (wick), которого
    в tf8-кэшах нет вовсе;
  * филл стартует после close 5m-бара → без look-ahead.

Результат: RUNS/temp/early_entry/<SYM>_<year>.pkl (signals+trades).
Запуск: python run_early_entry.py [workers=2]
"""
import logging
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import backtest.config as cfg  # noqa: E402

_tf8 = dict(cfg.BOT_TF_PROFILES["tf8"])
_tf8["confirm_timeframe"] = "5m"
cfg.BOT_TF_PROFILES["tf8_mss5"] = _tf8

from backtest.bot_aligned import run_bot_aligned_backtest  # noqa: E402

logging.disable(logging.INFO)
OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/early_entry"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]


def one(task):
    sym, year = task
    dst = f"{OUT}/{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    t0 = time.time()
    try:
        res = run_bot_aligned_backtest(
            since=f"{year}-01-01", until=f"{year}-12-31",
            profile="tf8_mss5", symbol=sym,
            limit_bars=1, pos_bars=12,
            save=False, quiet=True,
            detect_filters={"atr_enabled": False, "vol_enabled": False, "d_enabled": False},
            mss_on_ltf=False,
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    payload = {k: res.get(k) for k in ("trades", "signals", "profile", "symbol")}
    payload.update({"since": f"{year}-01-01", "until": f"{year}-12-31",
                    "entry_policy": "bot", "variant": "confirm_5m"})
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(payload, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: signals={len(payload.get('signals') or [])} trades={len(payload.get('trades') or [])} sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nworkers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    os.makedirs(OUT, exist_ok=True)
    skip = {("KAS", y) for y in (2020, 2021, 2022)}
    tasks = [(s, y) for s in PAIRS for y in YEARS if (s, y) not in skip]
    print(f"tasks: {len(tasks)} | workers: {nworkers}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nworkers) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] {msg}", flush=True)
    print(f"early_entry done in {time.time()-t0:.0f}s", flush=True)
