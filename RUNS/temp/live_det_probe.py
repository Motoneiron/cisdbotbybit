"""live_det_probe.py — bybit-детект (стек живого) на барах тех же кейсов. Окна 200 и 300."""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")

logging.disable(logging.CRITICAL)

import pandas as pd
import cisdbot as bot

CASES = [
    ("2024-01-01 11:25:00", "SHORT"),
    ("2024-01-04 09:35:00", "LONG"),
    ("2024-01-11 12:15:00", "SHORT"),
    ("2024-01-13 06:45:00", "SHORT"),
    ("2024-01-18 12:30:00", "LONG"),
    ("2024-01-20 00:30:00", "LONG"),
    ("2024-01-05 17:20:00", "LONG"),
]

import pickle

rows = pickle.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_filt/SOL_2024.pkl", "rb"))
print("live pkl записей:", len(rows))
print("htf_ratio [tf7]:", bot.CONFIG["tf7"].get("htf_ratio"))

# данные строим как live_filt_big
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")
import live_filt_big as lf

df1 = lf.load_1m(lf.PATHS["SOL"], "2024-01-01", "2024-02-01")
df = bot._resample_ohlcv(df1, "5m")
print("df5:", len(df), df.index[0], "..", df.index[-1])

for scan_s, d_want in CASES:
    scan = pd.Timestamp(scan_s)
    i = int(df.index.searchsorted(scan))
    if i < len(df) and df.index[i] != scan:
        i -= 1
    i = min(i, len(df) - 1)
    print(f"\n### {scan_s} ({d_want}) i={i}")
    for W in (200, 300):
        sl = df.iloc[max(0, i - W + 1) : i + 1]
        sigs = bot.detect_signals(
            sl, set(), htf_ratio=int(bot.CONFIG["tf7"]["htf_ratio"]), tf_name="tf7",
            df_confirm=None, min_sweep_atr=0.0,
        ) or []
        tag = f"W={W}"
        if not sigs:
            print(f"   {tag}: -")
        for s in sigs:
            print(f"   {tag}: {s.get('direction')} cbt={s.get('confirm_bar_time')} e={s.get('entry')}")
