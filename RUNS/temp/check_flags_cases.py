"""Сценарии данных на момент 20:00:05-08 UTC: какие дают (False,False) для окна 16:00."""
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
CUT = pd.Timestamp("2026-09-13 20:00")


def probe(name: str, sub: pd.DataFrame):
    df_htf = det.resample_to_htf(sub)
    try:
        idx = df_htf.index.get_loc(pd.Timestamp("2026-09-13 16:00"))
    except KeyError:
        print(f"{name:28} | нет бара 16:00 в df_htf | tail={list(df_htf.index[-2:])}")
        return
    if isinstance(idx, (slice,)) or hasattr(idx, "__len__"):
        print(f"{name:28} | get_loc вернул не-scalar: {idx}")
        return
    n = int(((sub.index >= pd.Timestamp("2026-09-13 16:00")) & (sub.index < CUT)).sum())
    last3 = list(df_htf.index[-3:])
    if idx < 1:
        print(f"{name:28} | idx={idx} (<1) -> return True,True | n={n} | tail={last3}")
        return
    c2 = df_htf.iloc[idx]
    c3 = df_htf.iloc[idx - 1]
    hh = bool(c2["high"] > c3["high"] and c2["close"] < c3["high"])
    ll = bool(c2["low"] < c3["low"] and c2["close"] > c3["low"])
    skip = "SKIP(idx>=len-1)" if idx >= len(df_htf) - 1 else ""
    print(f"{name:28} | idx={idx} len={len(df_htf)} {skip} | n={n} | c2 h/l/c={c2['high']}/{c2['low']}/{c2['close']} c3={c3['high']}/{c3['low']} | flags=({hh},{ll}) | tail={last3}")


full = df[df.index <= CUT]
print("сценарии (свечи KAS 5m, до 20:00 UTC):")
probe("полные (с баром 20:00)", full)
probe("без бара 20:00", full[:-1])
probe("без 20:00 и 19:55", full[:-2])
probe("без последних 3 (Лаг биржи)", full[:-3])
probe("без последних 5", full[:-5])
probe("без последних 10", full[:-10])
