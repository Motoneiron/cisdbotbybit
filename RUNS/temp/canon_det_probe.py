"""canon_det_probe.py — MEXC-детект (стек канона) на барах notseen-кейсов. Окна 200 и 300."""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

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

df = pd.read_csv(
    r"D:/databtcusdt/SOLUSDT-5m/SOLUSDT_5m_full_hdr.csv",
    usecols=["open_time", "open", "high", "low", "close", "volume"],
)
df.index = pd.to_datetime(df.pop("open_time"), unit="ms")
df = df.astype(float).sort_index()
print("df5:", len(df), df.index[0], "..", df.index[-1])
print("htf_ratio [tf7]:", bot.CONFIG["tf7"].get("htf_ratio"))

for scan_s, d_want in CASES:
    scan = pd.Timestamp(scan_s)
    i = int(df.index.searchsorted(scan))
    if i >= len(df) or df.index[i] != scan:
        i = int(df.index.searchsorted(scan, side="left")) - 1
    print(f"\n### {scan_s} ({d_want}) i={i}")
    for W in (200, 300):
        sl = df.iloc[max(0, i - W + 1) : i + 1]
        for msa in (0.0, 0.40):
            sigs = bot.detect_signals(
                sl, set(), htf_ratio=int(bot.CONFIG["tf7"]["htf_ratio"]), tf_name="tf7",
                df_confirm=None, min_sweep_atr=msa,
            ) or []
            tag = f"W={W} min_sweep_atr={msa}"
            if not sigs:
                print(f"   {tag}: -")
            for s in sigs:
                print(f"   {tag}: {s.get('direction')} cbt={s.get('confirm_bar_time')} e={s.get('entry')} fib={1 if s.get('fib_stretch_market') else 0} kind={bot._entry_kind_for_signal(s)}")
