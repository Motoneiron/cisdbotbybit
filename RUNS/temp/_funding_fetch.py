"""Фандинг с Bybit (v5 funding/history) для 10 пар, вся история → pkl+csv.
Пагинация НАЗАД (API отдаёт новейшие 200 записей в окне). Инкрементальное сохранение."""
import csv
import json
import pickle
import sys
import time
import urllib.request
from datetime import datetime, timezone

PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
OUT_PKL = r"D:/PYTHON/cisdbotbybit/RUNS/temp/funding_bybit.pkl"
OUT_CSV = r"D:/PYTHON/cisdbotbybit/RUNS/temp/funding_bybit.csv"
URL = "https://api.bybit.com/v5/market/funding/history"


def fetch_page(symbol, start_ms, end_ms, tries=4):
    last_err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(
                f"{URL}?category=linear&symbol={symbol}USDT&startTime={start_ms}&endTime={end_ms}&limit=200"
            )
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode())
            if d.get("retCode") != 0:
                raise RuntimeError(f"retCode={d.get('retCode')} {d.get('retMsg')}")
            return d["result"]["list"]
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{symbol} page failed after {tries} tries: {last_err!r}")


def fetch_pair(symbol):
    rows, seen = [], set()
    start = 1577836800000  # 2020-01-01
    end = int(time.time() * 1000)
    for _ in range(80):
        lst = fetch_page(symbol, start, end)
        if not lst:
            break
        new = 0
        for x in lst:
            ts = int(x["fundingRateTimestamp"])
            if ts not in seen:
                seen.add(ts)
                rows.append((symbol, ts, float(x["fundingRate"])))
                new += 1
        oldest = min(int(x["fundingRateTimestamp"]) for x in lst)
        if new == 0 or oldest <= start:
            break
        end = oldest - 1
        time.sleep(0.15)
    rows.sort(key=lambda t: t[1])
    return rows


def save(allrows):
    with open(OUT_PKL, "wb") as f:
        pickle.dump(allrows, f)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "ts_ms", "rate"])
        w.writerows(allrows)


if __name__ == "__main__":
    allrows = []
    for sym in PAIRS:
        try:
            r = fetch_pair(sym)
            if r:
                a = datetime.fromtimestamp(r[0][1] / 1000, tz=timezone.utc)
                b = datetime.fromtimestamp(r[-1][1] / 1000, tz=timezone.utc)
                print(f"{sym}: {len(r)} записей {a:%Y-%m-%d}..{b:%Y-%m-%d}", flush=True)
            else:
                print(f"{sym}: 0 записей", flush=True)
            allrows.extend(r)
            save(allrows)
        except Exception as e:
            print(f"{sym}: FAILED {e!r}", flush=True)
    print(f"saved: {OUT_PKL} / {OUT_CSV} | total: {len(allrows)}", flush=True)
