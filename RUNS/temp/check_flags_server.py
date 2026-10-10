"""Реплика проверки бота: KAS 5m -> 4h, свипы между 16:00 и 12:00 (для логирования)."""
import json
import urllib.request

import pandas as pd

url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=KASUSDT&interval=5&limit=500"
d = json.loads(urllib.request.urlopen(url, timeout=30).read())
rows = d["result"]["list"][::-1]
df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "turnover"])
df["t"] = pd.to_datetime(df["t"].astype("int64"), unit="ms")
df = df.set_index("t")[["open", "high", "low", "close", "volume"]].astype(float)

from detectors.cisd_htf import CISDDetector

det = CISDDetector(htf_ratio=240)
df_htf = det.resample_to_htf(df)
print("HTF последние 5:")
print(df_htf.tail(5).to_string())

idx = df_htf.index.get_loc(pd.Timestamp("2026-09-13 16:00"))
c2 = df_htf.iloc[idx]
c3 = df_htf.iloc[idx - 1]
print("c3 (=12:00):", c3.to_dict())
print("c2 (=16:00):", c2.to_dict())
print("has_high (bearish):", CISDDetector.htf_candles_sweep(c2, c3, True))
print("has_low  (bullish):", CISDDetector.htf_candles_sweep(c2, c3, False))
