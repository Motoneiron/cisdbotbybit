"""Проверка полей сигналов в filters-off сборке 09-11 (и backup для сравнения)."""
import pickle
import sys
from collections import Counter

paths = {
    "09-11 (filters-off)": r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/SOL_tf7_2024-01-01_2024-12-31.pkl",
    "backup (ATR/VOL on)": r"D:/PYTHON/CISDBOT/RUNS/backup_bot_aligned_before_filteroff/bot_aligned/SOL_tf7_2024-01-01_2024-12-31.pkl",
}
EXTRA = ["prior_touches", "quality_score", "quality", "psl_probability", "psl_quartile",
         "soft_dow", "sw_atr", "vol_ratio", "start_n", "never"]
for label, p in paths.items():
    try:
        c = pickle.load(open(p, "rb"))
    except Exception as e:
        print(label, "LOAD FAIL", e)
        continue
    sigs = c.get("signals") or []
    print(f"\n=== {label}: sig={len(sigs)}")
    if not sigs:
        continue
    keys = set(sigs[0].keys())
    for k in EXTRA:
        cnt = sum(1 for s in sigs if k in s)
        print(f"  {k:16s}: {cnt}/{len(sigs)}")
    # полный список ключей
    print("  all keys:", sorted(keys))
