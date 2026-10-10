"""Догрузка 5m свечей с Bybit за период живых сделок (для сверки с бэктестом).

Кэши бэктеста кончаются 2026-09-06, а живые сделки идут с 2026-09-16, поэтому
движок физически не может их увидеть. Тянем публичные клайны linear-перпов
(без ключей) и кладём в формате, который понимает backtest.data.load_ltf(csv=...).

Запас истории до первой сделки нужен под прогрев: ATR14 на 8H = ~5 суток,
структура базы смотрит дальше, поэтому берём с 20 августа.

Запуск: python fetch_bybit_5m.py
"""
from __future__ import annotations

import os
import time

import pandas as pd
import requests

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/data_live_sep2026"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
SINCE = "2026-08-20"
UNTIL = "2026-09-23"
URL = "https://api.bybit.com/v5/market/kline"


def fetch(sym: str) -> pd.DataFrame:
    start = int(pd.Timestamp(SINCE).value // 1_000_000)
    end = int(pd.Timestamp(UNTIL).value // 1_000_000)
    rows: list[list] = []
    cur = start
    step = 1000 * 5 * 60_000
    while cur < end:
        # Bybit отдаёт последние limit баров ДО end, поэтому окно задаём явно,
        # иначе на любом диапазоне вернутся только свежие 1000 свечей
        win_end = min(cur + step, end)
        r = requests.get(
            URL,
            params={
                "category": "linear", "symbol": f"{sym}USDT", "interval": "5",
                "start": cur, "end": win_end, "limit": 1000,
            },
            timeout=20,
        )
        r.raise_for_status()
        js = r.json()
        if js.get("retCode") != 0:
            raise RuntimeError(f"{sym}: {js.get('retMsg')}")
        lst = js["result"]["list"]
        if not lst:
            break
        lst = sorted(lst, key=lambda x: int(x[0]))
        rows += lst
        nxt = max(int(lst[-1][0]) + 5 * 60_000, cur + step)
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    df["timestamp"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    return df[["timestamp", "open", "high", "low", "close", "volume"]].astype(
        {c: float for c in ("open", "high", "low", "close", "volume")}
    )


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in PAIRS:
        dst = f"{OUT}/{s}USDT_5m_bybit.csv"
        if os.path.exists(dst):
            print(f"skip {s}")
            continue
        d = fetch(s)
        d.to_csv(dst, index=False)
        print(f"{s}: {len(d)} баров {d.timestamp.iloc[0]} .. {d.timestamp.iloc[-1]}", flush=True)
