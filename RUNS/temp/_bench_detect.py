import logging
import sys
import time

import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
logging.disable(logging.CRITICAL)
import cisdbot as bot

raw = pd.read_csv(r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_sep\SOLUSDT_1m.csv")
raw["dt"] = pd.to_datetime(raw["timestamp"])
m1 = raw.set_index("dt")[["open", "high", "low", "close", "volume"]]
df5 = bot._resample_ohlcv(m1, "5m")
seen = set()
htf = 240
# warmup one call
sl = df5.iloc[:300]
bot.detect_signals(sl, seen, htf_ratio=htf, tf_name="tf7", df_confirm=None, min_sweep_atr=0.4)
t0 = time.perf_counter()
n = 40
for i in range(300, 300 + n):
    sl = df5.iloc[i - 299 : i + 1]
    bot.detect_signals(sl, seen, htf_ratio=htf, tf_name="tf7", df_confirm=None, min_sweep_atr=0.4)
dt = time.perf_counter() - t0
print(f"{n} calls {dt:.2f}s  {1000*dt/n:.1f} ms/call")
