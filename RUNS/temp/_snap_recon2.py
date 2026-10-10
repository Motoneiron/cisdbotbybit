"""Проверка: какие файлы выбирал final_early_sum.py + что в них."""
import glob
import pickle
import re
import sys
from collections import Counter

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

print("=== все bot_aligned dirs:")
dirs = sorted(set(p.replace("\\", "/").rsplit("/bot_aligned/", 1)[0] for p in
                  glob.glob(r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/*.pkl")))
for d in dirs:
    print("  ", d)

# реплика выбора final_early_sum.py
for sym, prof in (("SOL", "tf7"), ("ETH", "tf7"), ("SOL", "tf8")):
    all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{prof}_*.pkl"),
                       key=lambda p: p.replace("\\", "/"))
    best = {}
    for f in all_files:
        name = f.replace("\\", "/").split("/")[-1]
        m = re.match(rf"{sym}_{prof}_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
        if m:
            best[m.group(1)] = f
    print(f"\n=== {sym} {prof}: выбранные файлы:")
    for year, f in sorted(best.items()):
        c = pickle.load(open(f, "rb"))
        sigs = c.get("signals") or []
        trades = c.get("trades") or []
        dfilter = None
        for s in sigs:
            dfilter = s.get("detect_filters")
            if dfilter:
                break
        has_touches = sum(1 for s in sigs if "prior_touches" in s)
        has_q = sum(1 for s in sigs if "quality_score" in s)
        lim = sum(1 for t in trades if t.get("entry_kind") == "LIMIT")
        short = f.replace("D:/PYTHON/CISDBOT/RUNS/", "")
        print(f"  {year}: {short} | sig={len(sigs)} lim={lim} | detect_filters={dfilter} | touches={has_touches}/{len(sigs)} qscore={has_q}/{len(sigs)}")
