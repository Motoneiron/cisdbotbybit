"""Проверка снятий: KAS 8H-свечи [08:00] и [16:00] — есть ли high/low-свип."""
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
o = ex.fetch_ohlcv("KAS/USDT:USDT", "30m", limit=200)
df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
df["dt"] = pd.to_datetime(df.ts, unit="ms", utc=True)
df = df.set_index("dt")[["open", "high", "low", "close", "volume"]]
df.index = df.index.tz_localize(None)

det = bot.CISDDetector(htf_ratio=480)
h8 = det.resample_to_htf(df)
print("8H свечи (хвост):")
print(h8.tail(4).to_string())

for i, c2t in enumerate(h8.index):
    if str(c2t) not in ("2026-09-12 00:00:00", "2026-09-12 08:00:00", "2026-09-12 16:00:00"):
        continue
    if i < 1:
        continue
    c2 = h8.iloc[i]; c3 = h8.iloc[i - 1]
    has_high = bot.CISDDetector.htf_candles_sweep(c2, c3, True)
    has_low = bot.CISDDetector.htf_candles_sweep(c2, c3, False)
    print(f"\n[{c2t}] O={c2['open']:.4f} H={c2['high']:.4f} L={c2['low']:.4f} C={c2['close']:.4f}")
    print(f"  prev H={c3['high']:.4f} L={c3['low']:.4f}")
    print(f"  has_high={has_high} has_low={has_low}")
    print(f"  => если SHORT-кандидат на [{c2t}]: {'снять' if not has_high else 'оставить'}; "
          f"LONG: {'снять' if not has_low else 'оставить'}")
