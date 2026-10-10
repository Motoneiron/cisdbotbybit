# Диагностика честного якоря sw (бар свипа): печатает trigger/confirm/индексы для реальных сигналов SOL.
import sys
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
import logging
logging.disable(logging.CRITICAL)
import numpy as np
import pandas as pd
import cisdbot as bot
import live_tf_grid as g

df1 = g.load_1m(g.PATHS["SOL"], "2025-01-01", "2025-03-01")
df_tf = bot._resample_ohlcv(df1, "15m")
src = g._resample_local(bot, df1, "15m")
ema = src["close"].ewm(span=21, adjust=False, min_periods=21).mean()
slope_full = (ema / ema.shift(1) - 1.0).to_numpy(dtype=float)
ct = (src.index + pd.Timedelta(minutes=15)).to_numpy()
ii = np.searchsorted(ct, df_tf.index.to_numpy(), side="right") - 1
n = len(slope_full)
slope_arr = np.where((ii >= 0) & (ii < n) & (n > 0), slope_full[np.clip(ii, 0, max(0, n - 1))], np.nan)
idx = df_tf.index

WIN = 300
seen = set()
cnt = 0
nan_sw = 0
bad_gap = 0
for i in range(WIN, len(df_tf)):
    sl = df_tf.iloc[i - (WIN - 1): i + 1]
    sigs = bot.detect_signals(sl, seen, htf_ratio=240, tf_name="tf1", df_confirm=None, min_sweep_atr=0.40) or []
    for s in sigs:
        h = str(s.get("hash") or "")
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        tr = str(s.get("trigger_bar_time") or "")
        cb = str(s.get("confirm_bar_time") or "")
        try:
            kk = int(np.searchsorted(idx.to_numpy(), np.datetime64(pd.Timestamp(tr)), side="right"))
        except Exception as e:
            print("PARSE_FAIL", tr, e, flush=True)
            continue
        sw_idx = kk - 1
        sw_open = idx[sw_idx] if 0 <= sw_idx < len(idx) else None
        sw_sl = slope_arr[sw_idx] if 0 <= sw_idx < len(slope_arr) else float("nan")
        lc_sl = slope_arr[i - 1]
        gap = i - sw_idx
        cnt += 1
        if not (sw_sl == sw_sl):
            nan_sw += 1
        if gap <= 0:
            bad_gap += 1
        print(f"#{cnt} scan={idx[i]} tr={tr[:19]} cb={cb[:19]} sw_idx={sw_idx} sw_open={sw_open} gap_bars={gap} sw_slope={sw_sl:.6f} lc_slope={lc_sl:.6f} dir={s.get('direction')}", flush=True)
        if cnt >= 12:
            print(f"STOP after 12; nan_sw={nan_sw} bad_gap={bad_gap}", flush=True)
            sys.exit(0)
print(f"TOTAL sigs={cnt} sw_nan={nan_sw} bad_gap={bad_gap}", flush=True)
