"""Все 10 пар: был ли свип 16:00 vs 12:00 (по данным Bybit 4H)."""
import json
import urllib.request

import pandas as pd

syms = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
print(f"{'пара':5} | {'c3=12:00 (h/l)':22} | {'c2=16:00 (h/l/c)':26} | high_sw | low_sw")
for s in syms:
    try:
        url = (f"https://api.bybit.com/v5/market/kline?category=linear&symbol={s}USDT"
               f"&interval=240&limit=12")
        d = json.loads(urllib.request.urlopen(url, timeout=30).read())
        rows = d["result"]["list"][::-1]
        df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "to"])
        df["t"] = pd.to_datetime(df["t"].astype("int64"), unit="ms")
        df = df.set_index("t").astype({"o": float, "h": float, "l": float, "c": float})
        c2 = df.loc[pd.Timestamp("2026-09-13 16:00")]
        c3 = df.loc[pd.Timestamp("2026-09-13 12:00")]
        hh = c2.h > c3.h and c2.c < c3.h
        ll = c2.l < c3.l and c2.c > c3.l
        print(f"{s:5} | {c3.h:>10}/{c3.l:<10} | {c2.h:>10}/{c2.l}/{c2.c:<0} | {str(hh):7} | {ll}")
    except Exception as e:
        print(f"{s:5} | ERROR: {e}")
