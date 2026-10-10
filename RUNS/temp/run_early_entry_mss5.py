"""Ранний вход №2: прогон движка с confirm_timeframe=5m И mss_on_ltf=True.

Отличие от run_early_entry.py: тот прогон шёл с mss_on_ltf=False — MSS оставался
на 30m, поэтому подтверждение фактически НЕ смещалось (wick-класс = 0%, все три
политики совпали), и вопрос «5m entry → 30m invalidation» остался не измеренным.

Здесь подтверждение (MSS) ищется НА 5m-барах (как в живом боте ДО фикса 16.09):
  * профиль tf8_mss5 = tf8 + confirm_timeframe="5m" → сигналы по 5m-конфирму,
    включая класс «30m-свеча только проткнула уровень фитилём» (wick);
  * филл стартует после close 5m-бара (честный якорь) → без look-ahead.

Результат: RUNS/temp/early_entry_mss5/<SYM>_<year>.pkl (signals+trades).
Запуск: python run_early_entry_mss5.py [workers=2] [only=SYM:YEAR]
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
import cisdbot as _mexc  # noqa: E402

# ⚠️ detect_signals берёт confirm_timeframe из CONFIG СВОЕГО модуля (MEXC-бот),
# а профиля tf8_mss5 там нет вовсе (в CONFIG только tf0..tf7) → без этой записи
# df_mss остаётся главным ТФ и 5m-подтверждение НЕ включается. Проверено на
# smoke 21.09: без записи поток совпал с 30m-каноном 1:1 (521/521 сигналов).
_mexc.CONFIG["tf8_mss5"] = {
    "timeframe": "30m",
    "confirm_timeframe": "5m",
    "htf_ratio": 480,
    "limit_h": 0.5,
    "position_h": 6,
    "ohlcv": 500,
    "label": "30m -> 8H (5m MSS)",
}

logging.disable(logging.INFO)
OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/early_entry_mss5"
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
            mss_on_ltf=True,
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    payload = {k: res.get(k) for k in ("trades", "signals", "profile", "symbol")}
    payload.update({"since": f"{year}-01-01", "until": f"{year}-12-31",
                    "entry_policy": "bot", "variant": "confirm_5m_mss5"})
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(payload, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: signals={len(payload.get('signals') or [])} trades={len(payload.get('trades') or [])} sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    only = None
    nworkers = 2
    for a in sys.argv[1:]:
        if ":" in a:
            only = a
        else:
            nworkers = int(a)
    os.makedirs(OUT, exist_ok=True)
    skip = {("KAS", y) for y in (2020, 2021, 2022)}
    if only:
        sym, ys = only.split(":")
        tasks = [(sym.upper(), int(ys))]
    else:
        tasks = [(s, y) for s in PAIRS for y in YEARS if (s, y) not in skip]
    print(f"tasks: {len(tasks)} | workers: {nworkers} | mss_on_ltf=True", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nworkers) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] {msg}", flush=True)
    print(f"early_entry_mss5 done in {time.time()-t0:.0f}s", flush=True)
