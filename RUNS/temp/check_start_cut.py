"""Перебор: с какого момента начинаются данные, чтобы получить (False,False) для 16:00."""
import json
import urllib.request

import pandas as pd

url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=KASUSDT&interval=5&limit=500"
d = json.loads(urllib.request.urlopen(url, timeout=30).read())
rows = d["result"]["list"][::-1]
df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "turnover"])
df["t"] = pd.to_datetime(df["t"].astype("int64"), unit="ms")
df = df.set_index("t")[["open", "high", "low", "close", "volume"]].astype(float)
df = df[df.index <= pd.Timestamp("2026-09-13 20:00")]

from detectors.cisd_htf import CISDDetector

det = CISDDetector(htf_ratio=240)
hits = []
for start in df.index:
    if start < pd.Timestamp("2026-09-13 06:00"):
        continue
    sub = df[df.index >= start]
    df_htf = det.resample_to_htf(sub)
    try:
        idx = df_htf.index.get_loc(pd.Timestamp("2026-09-13 16:00"))
    except KeyError:
        continue
    if not isinstance(idx, int):
        continue
    if idx < 1:
        continue
    c2 = df_htf.iloc[idx]
    c3 = df_htf.iloc[idx - 1]
    hh = bool(c2["high"] > c3["high"] and c2["close"] < c3["high"])
    ll = bool(c2["low"] < c3["low"] and c2["close"] > c3["low"])
    if not hh and not ll:
        hits.append((start, c2["high"], c2["low"], c2["close"], c3["high"], c3["low"], c3["close"], idx))

print(f"найдено (F,F) начал: {len(hits)}")
for h in hits[:15]:
    print(f"start={h[0]} | c2(h/l/c)={h[1]}/{h[2]}/{h[3]} | c3={h[4]}/{h[5]}/{h[6]} | idx={h[7]}")
