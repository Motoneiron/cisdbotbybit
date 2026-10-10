"""Инвентаризация вариантов кэшей: какие population существуют и что выбрал final_early."""
import glob
import pickle
import re
import sys
from collections import Counter

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

# 1) ВСЕ файлы SOL tf7 — по годам и папкам
print("### SOL tf7 — все варианты:")
files = sorted(glob.glob(r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf7_*.pkl"),
               key=lambda p: p.replace("\\", "/"))
for f in files:
    name = f.replace("\\", "/")
    rel = name.replace("D:/PYTHON/CISDBOT/RUNS/", "")
    try:
        c = pickle.load(open(f, "rb"))
    except Exception as e:
        print(f"  {rel} | LOAD FAIL {e!r}")
        continue
    sigs = c.get("signals") or []
    trades = c.get("trades") or []
    dfs = Counter(str(s.get("detect_filters")) for s in sigs)
    lim = sum(1 for t in trades if t.get("entry_kind") == "LIMIT")
    print(f"  {rel} | sig={len(sigs):4d} lim={lim:4d} | {dict(dfs)}")

# 2) что лежит в папках 09-х чисел
print("\n### содержимое папок 2026-09-*:")
for d in ("2026-09-06", "2026-09-07", "2026-09-08", "2026-09-11", "2026-09-12", "2026-09-13"):
    fs = glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/{d}/bot_aligned/*.pkl")
    print(f"  {d}: {len(fs)} файлов", sorted(f.split("/")[-1].split('\\')[-1] for f in fs)[:8])

# 3) кросс-таб final_early pkl: sym x year
with open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/final_early_trades.pkl", "rb") as fh:
    obj = pickle.load(fh)
xt = Counter((t["sym"], t["year"]) for t in obj)
print("\n### final_early pkl: sym x year:")
syms = sorted(set(s for s, y in xt))
years = sorted(set(y for s, y in xt))
print("        " + " ".join(f"{y[-2:]:>5}" for y in years))
for s in syms:
    row = " ".join(f"{xt.get((s, y), 0):>5}" for y in years)
    print(f"  {s:4s} {row}")
