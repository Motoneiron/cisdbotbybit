"""Проверка снятий tf7 (4H): KAS свечи [16:00], [20:00]."""
import importlib.util
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import ccxt
import pandas as pd

spec = importlib.util.spec_from_file_location("cisdbot_mod", r"D:/PYTHON/cisdbotbybit/cisdbot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

ex = ccxt.bybit({"defaultType": "swap"})
o = ex.fetch_ohlcv("KAS/USDT:USDT", "5m", limit=1000)
df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
df["dt"] = pd.to_datetime(df.ts, unit="ms", utc=True)
df = df.set_index("dt")[["open", "high", "low", "close", "volume"]]
df.index = df.index.tz_localize(None)

det = bot.CISDDetector(htf_ratio=240)   # 4H
h4 = det.resample_to_htf(df)
print("4H свечи (хвост):")
print(h4.tail(5).to_string())

for c2t in ("2026-09-12 12:00:00", "2026-09-12 16:00:00", "2026-09-12 20:00:00"):
    locs = [i for i, t in enumerate(h4.index) if str(t) == c2t]
    if not locs:
        print(f"[{c2t}] нет в данных")
        continue
    i = locs[0]
    if i < 1:
        continue
    c2 = h4.iloc[i]; c3 = h4.iloc[i - 1]
    has_high = bot.CISDDetector.htf_candles_sweep(c2, c3, True)
    has_low = bot.CISDDetector.htf_candles_sweep(c2, c3, False)
    print(f"\n[{c2t}] H={c2['high']:.4f} L={c2['low']:.4f} C={c2['close']:.4f} | "
          f"prev H={c3['high']:.4f} L={c3['low']:.4f}")
    print(f"  has_high={has_high} has_low={has_low} => SHORT: {'снять' if not has_high else 'ок'}; "
          f"LONG: {'снять' if not has_low else 'ок'}")
