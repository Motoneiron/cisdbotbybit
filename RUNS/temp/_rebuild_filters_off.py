"""Пересборка filters-off кэшей: 10 пар × tf7/tf8 × 2020-2026.
Изолированный output: RUNS/filters_off_full/ (вне glob-путей bot_aligned).
Запуск: python _rebuild_filters_off.py [workers=6]
Резюмируемый: готовые файлы пропускаются."""
import logging
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

logging.disable(logging.INFO)

OUT = r"D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]


def one(task):
    sym, prof, year = task
    dst = f"{OUT}/{sym}_{prof}_{year}-01-01_{year}-12-31.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {prof} {year}"
    from backtest.bot_aligned import run_bot_aligned_backtest
    t0 = time.time()
    try:
        res = run_bot_aligned_backtest(
            since=f"{year}-01-01", until=f"{year}-12-31",
            profile=prof, symbol=sym,
            limit_bars=4 if prof == "tf7" else 1,
            pos_bars=192 if prof == "tf7" else 12,
            save=False, quiet=True,
            detect_filters={"atr_enabled": False, "vol_enabled": False, "d_enabled": False},
            mss_on_ltf=False if prof == "tf8" else None,
        )
        payload = {k: res.get(k) for k in ("trades", "signals", "profile", "symbol")}
        payload["since"] = f"{year}-01-01"
        payload["until"] = f"{year}-12-31"
        payload["entry_policy"] = "bot"
        payload["detect_filters"] = {"atr": False, "vol": False, "d": False}
        with open(dst + ".tmp", "wb") as f:
            pickle.dump(payload, f)
        os.replace(dst + ".tmp", dst)
        nt = len(payload.get("trades") or [])
        return f"OK {sym} {prof} {year}: trades={nt} sec={time.time()-t0:.0f}"
    except Exception as e:
        return f"FAIL {sym} {prof} {year}: {e!r} sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nworkers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    os.makedirs(OUT, exist_ok=True)
    skip = {("KAS", y) for y in (2020, 2021, 2022)}
    tasks = [(s, p, y) for s in PAIRS for p in ("tf7", "tf8") for y in YEARS if (s, y) not in skip]
    print(f"tasks: {len(tasks)} | workers: {nworkers}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    done = 0
    with Pool(nworkers) as pool:
        for r in pool.imap_unordered(one, tasks):
            done += 1
            print(f"[{done}/{len(tasks)}] +{time.time()-t0:.0f}s {r}", flush=True)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)
