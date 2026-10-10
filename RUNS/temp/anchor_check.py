"""anchor_check.py — проверка якоря cb: нет ли look-ahead (доступно ли значение наклона в момент решения).

Логика live-модели: скан на баре i (open=13:35) при конфирме i-1 (open=13:30).
Момент решения = close конфирма = open бара i.
Для честности гейт должен брать наклон, вычисленный по ЗАКРЫТЫМ барам <= i-1.
Проверяем фактически: какой бар берёт код для 'cb' и для 'tb', и когда его close доступен.
"""
import sys
import logging as _log

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
_log.disable(_log.CRITICAL)
import cisdbot as bot  # noqa: E402

# загрузка ADA за узкое окно (как load_1m в live_tf_grid)
path = r"D:\databtcusdt\ADAUSDT-1m-merged.csv"
t0 = pd.Timestamp("2024-01-11")
t1 = pd.Timestamp("2024-01-12")
parts = []
for chunk in pd.read_csv(path, usecols=["open_time", "open", "high", "low", "close", "volume"], chunksize=500_000):
    ot = pd.to_datetime(chunk["open_time"], unit="ms")
    m = (ot >= t0) & (ot < t1)
    if not m.any():
        continue
    sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
    sub.index = ot[m]
    parts.append(sub)
df1 = pd.concat(parts).sort_index()
print("1m баров:", len(df1))

df_tf = bot._resample_ohlcv(df1, "5m")
print("5m баров:", len(df_tf))
print("индекс хвост:", df_tf.index[-4:].tolist())

# пример из pkl: scan=13:35, cbt=13:30
cb_ts = pd.Timestamp("2024-01-11 13:30:00")
scan_ts = pd.Timestamp("2024-01-11 13:35:00")
idx = df_tf.index.to_numpy()
jj = int(np.searchsorted(idx, np.datetime64(cb_ts), side="right"))
print(f"\ncbt={cb_ts}  scan={scan_ts}")
print(f"searchsorted(cbt, right) = {jj} -> бар с open = {df_tf.index[jj]}")
i_scan = df_tf.index.get_loc(scan_ts)
print(f"индекс бара scan (open 13:35) = {i_scan}")
print(f"бар конфирма (open 13:30) = индекс {i_scan - 1} (open {df_tf.index[i_scan-1]})")

# slope (как в live_tf_grid: ema/ema.shift-1)
ema = df_tf["close"].ewm(span=13, adjust=False, min_periods=13).mean()
slope = (ema / ema.shift(1) - 1.0).to_numpy(dtype=float)
for k in range(i_scan - 2, min(i_scan + 3, len(df_tf))):
    bar_open = df_tf.index[k]
    bar_close = bar_open + pd.Timedelta(minutes=5)
    print(f"  бар[{k}] open={bar_open} close={bar_close}  slope={slope[k]:.6f}")

print(f"\n--> Для cb берётся бар[{jj}] = {df_tf.index[jj] if jj < len(df_tf) else 'OUT'}")
print(f"    Его close доступен в: {(df_tf.index[jj] + pd.Timedelta(minutes=5)) if jj < len(df_tf) else '-'}")
print(f"    Момент решения (close конфирма) = {scan_ts}")
if jj < len(df_tf):
    avail = df_tf.index[jj] + pd.Timedelta(minutes=5)
    print(f"    LOOK-AHEAD: {avail > scan_ts} (разница {(avail - scan_ts).total_seconds()/60:.0f} мин)")
