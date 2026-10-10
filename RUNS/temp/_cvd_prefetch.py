"""Prefetch aggTrades (S3-эндпоинт, data.binance.vision недоступен с этой машины) для дней сделок пары.

Дни = {date(decision−12ч), date(decision)} — покрывает pre-историю и день сделки.
Использование: python _cvd_prefetch.py SOL [--workers 4]
"""
import argparse
import os
import sys
import time
import urllib.request

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/futures/um/daily/aggTrades"
STREAM = r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_off_v1_v2.pkl"


def days_for(sym: str):
    df = pd.read_pickle(STREAM)
    g = df[df.sym == sym]
    dec = pd.to_datetime(g["decision_at"])
    days = set()
    for t in dec:
        days.add((t - pd.Timedelta(hours=12)).date())
        days.add(t.date())
    return sorted(days)


def fetch_one(sym: str, d, outdir: str) -> str:
    fname = f"{sym}USDT-aggTrades-{d}.zip"
    path = os.path.join(outdir, fname)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return "skip"
    url = f"{BASE}/{sym}USDT/{fname}"
    tmp = path + ".part"
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            if len(data) < 100:
                raise RuntimeError(f"too small: {len(data)}")
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            return "ok"
        except Exception as e:
            last = e
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            time.sleep(1.5)
    return f"fail {last!r}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sym")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()
    outdir = args.outdir or rf"D:/PYTHON/cisdbotbybit/RUNS/temp/cvd/{args.sym}USDT"
    os.makedirs(outdir, exist_ok=True)
    days = days_for(args.sym)
    print(f"{args.sym}: {len(days)} уникальных дней сделок ({days[0]}..{days[-1]})", flush=True)
    ok = skip = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, args.sym, d, outdir): d for d in days}
        done = 0
        for f in as_completed(futs):
            done += 1
            r = f.result()
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                fail += 1
                print(f"  {futs[f]}: {r}", flush=True)
            if done % 50 == 0:
                print(f"[{done}/{len(days)}] ok={ok} skip={skip} fail={fail} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"DONE ok={ok} skip={skip} fail={fail} в {time.time()-t0:.0f}s → {outdir}", flush=True)


if __name__ == "__main__":
    main()
