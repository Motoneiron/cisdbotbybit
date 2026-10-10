"""probe_1205.py — точечный разбор: почему tb-набор потерял сделку 12-05 03:55 (и что с 10-08).

Воспроизводим решение walk для конкретных сканов: сигнал из detect_signals + обе ветки гейта.
"""
import sys
import logging as _log

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
_log.disable(_log.CRITICAL)
import cisdbot as bot  # noqa: E402

path = r"D:\databtcusdt\ADAUSDT-1m-merged.csv"
t0 = pd.Timestamp("2024-10-01")
t1 = pd.Timestamp("2024-12-10")
parts = []
for chunk in pd.read_csv(path, usecols=["open_time", "open", "high", "low", "close", "volume"], chunksize=1_000_000):
    ot = pd.to_datetime(chunk["open_time"], unit="ms")
    m = (ot >= t0) & (ot < t1)
    if not m.any():
        continue
    sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
    sub.index = ot[m]
    parts.append(sub)
df1 = pd.concat(parts).sort_index()
print("1m баров:", len(df1), flush=True)
df_tf = bot._resample_ohlcv(df1, "5m")
ema = df_tf["close"].ewm(span=13, adjust=False, min_periods=13).mean()
slope = (ema / ema.shift(1) - 1.0).to_numpy(dtype=float)
THR = 0.0002

for scan_s, cbt_s in (("2024-12-05 03:55:00", "2024-12-05 03:50:00"),
                      ("2024-10-08 13:45:00", "2024-10-08 13:35:00")):
    scan = pd.Timestamp(scan_s)
    cbt = pd.Timestamp(cbt_s)
    i = int(df_tf.index.get_loc(scan))
    jj = int(np.searchsorted(df_tf.index.to_numpy(), np.datetime64(cbt), side="right"))
    print(f"\n=== scan={scan} cbt={cbt} i={i} jj={jj} (jj-i={jj-i})", flush=True)
    print(f"  slope[bar i={df_tf.index[i]}]: {slope[i]:+.6f}", flush=True)
    print(f"  slope[bar jj={df_tf.index[jj]}]: {slope[jj]:+.6f}", flush=True)
    # сам сигнал: детектор на окне до i
    sl = df_tf.iloc[i - 299: i + 1]
    sigs = bot.detect_signals(sl, set(), htf_ratio=8, tf_name="tf7", df_confirm=None, min_sweep_atr=0.40) or []
    mine = [s for s in sigs if str(s.get("confirm_bar_time") or "").startswith(cbt_s[:16])]
    print(f"  сигналов всего: {len(sigs)}; с нашим конфирмом: {len(mine)}", flush=True)
    for s in mine:
        print(f"    dir={s.get('direction')} trigger={s.get('trigger_bar_time')} cbt={s.get('confirm_bar_time')}", flush=True)
    # применим гейт как в walk
    for gate, sv in (("tb", slope[i]), ("cb", slope[jj])):
        skip = False
        if sv == sv:
            if (("LONG" in str(mine[0].get("direction")) and sv <= THR) or
                    ("SHORT" in str(mine[0].get("direction")) and sv >= -THR)):
                skip = True
        print(f"  гейт {gate}: sv={sv:+.6f} -> {'SKIP' if skip else 'pass'}", flush=True)
print("\nDONE", flush=True)
