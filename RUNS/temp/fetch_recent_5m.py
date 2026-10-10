"""Загрузка свежих 5m OHLCV с Bybit (linear USDT perp) в отдельную папку,
чтобы прогнать бэк-движок на периодах, которых нет в датасете (он кончается 2026-05-22).

Пишем ТОЛЬКО в RUNS/temp/data_recent/ — исходные датасеты не трогаем.
"""
import os
import time

import ccxt
import pandas as pd

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/data_recent"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
START = "2026-07-25T00:00:00Z"     # ~7 недель прогрева перед 15.09
END = "2026-09-18T12:00:00Z"

os.makedirs(OUT, exist_ok=True)
ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})

since_ms = int(pd.Timestamp(START).timestamp() * 1000)
end_ms = int(pd.Timestamp(END).timestamp() * 1000)

for sym in PAIRS:
    path = f"{OUT}/{sym}USDT_5m_recent.csv"
    if os.path.exists(path):
        print(f"skip {sym}")
        continue
    market = f"{sym}/USDT:USDT"
    got, cursor = [], since_ms
    while cursor < end_ms:
        try:
            batch = ex.fetch_ohlcv(market, "5m", since=cursor, limit=1000)
        except Exception as e:
            print(f"  {sym} retry after {e!r}")
            time.sleep(3)
            continue
        if not batch:
            break
        got += batch
        last = batch[-1][0]
        if last <= cursor:
            break
        cursor = last + 300_000
        if len(got) % 10000 < 1000:
            print(f"  {sym}: {len(got)} баров, до {pd.to_datetime(last, unit='ms')}")
    df = pd.DataFrame(got, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    df = df[df["ts"] <= end_ms]
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms").dt.strftime("%Y-%m-%d %H:%M:%S")
    out = df[["timestamp", "open", "high", "low", "close", "volume"]]
    out.to_csv(path, index=False)
    print(f"{sym}: {len(out)} баров, {out['timestamp'].iloc[0]} → {out['timestamp'].iloc[-1]} -> {path}")
