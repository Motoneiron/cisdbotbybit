"""Probe4: полный дамп полей сигналов кейсов — что видит детект."""
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

import logging

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

import cisdbot as bot  # noqa: E402
import live_filt_big as lfb  # noqa: E402

df1 = lfb.load_1m(lfb.PATHS["SOL"], "2023-12-28", "2024-02-15")
df5 = bot._resample_ohlcv(df1, "5m")

CASES = [
    ("live-only", "2024-01-01 11:25:00", "SHORT"),
    ("live-only", "2024-01-04 09:35:00", "LONG"),
    ("live-only", "2024-01-05 17:20:00", "LONG"),
    ("live-only", "2024-01-06 22:00:00", "LONG"),
    ("live-only", "2024-01-07 14:35:00", "SHORT"),
    ("canon-only", "2024-01-07 02:20:00", "SHORT"),
    ("canon-only", "2024-01-14 14:20:00", "LONG"),
    ("canon-only", "2024-01-18 03:20:00", "LONG"),
    ("canon-only", "2024-01-23 22:20:00", "LONG"),
]

INTEREST = [
    "timestamp", "direction", "entry", "stop", "tp", "hash",
    "confirm_bar_time", "trigger_bar_time", "sweep_close_bar_time",
    "htf_time", "htf_sweep_level", "_fill_not_before", "prior_touches",
    "trigger_idx", "confirm_idx", "entry_kind",
]

for tag, ts_s, want in CASES:
    ts = pd.Timestamp(ts_s)
    i0 = df5.index.get_loc(ts)
    print("#" * 110)
    print(f"{tag} | {ts_s} | {want}")
    seen = set()
    for i in range(i0 - 18, i0 + 13):
        sl = df5.iloc[max(0, i - 299) : i + 1]
        out = bot.detect_signals(sl, set(), htf_ratio=240, tf_name="tf7", df_confirm=None) or []
        for s in out:
            if str(s.get("direction")) != want:
                continue
            h = str(s.get("hash") or "")[:16]
            if h in seen:
                continue
            cbt = str(s.get("confirm_bar_time") or "")
            if not cbt:
                continue
            c = pd.Timestamp(cbt)
            if abs((c - ts).total_seconds()) > 3600 * 5:
                continue
            seen.add(h)
            print(f"-- найден на баре {df5.index[i]}")
            for k in INTEREST:
                if k in s and s[k] is not None:
                    print(f"     {k} = {s[k]}")
