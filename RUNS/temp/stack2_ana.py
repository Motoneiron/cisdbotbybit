"""stack2_ana.py — категорийные агрегаты ночных сеток (30.09/01.10): alloff / hold / limit."""
import glob
import os
import pickle

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"
GROUPS = [
    ("BAZA foff (5ч/16ч)", "tf1lc15_foff"),
    ("ALLOFF (свип off)", "tf1lc15_alloff"),
    ("HOLD 12ч", "tf1lc15_foff_h12"),
    ("HOLD 8ч", "tf1lc15_foff_h8"),
    ("HOLD 6ч", "tf1lc15_foff_h6"),
    ("LIMIT 2ч", "tf1lc15_l2h"),
    ("LIMIT 1ч", "tf1lc15_l1h"),
    ("LIMIT 30м", "tf1lc15_l30m"),
    ("LIMIT 15м", "tf1lc15_l15m"),
]

for label, m in GROUPS:
    rows = []
    for f in sorted(glob.glob(os.path.join(BASE, m, "*.pkl"))):
        rows += pickle.load(open(f, "rb"))
    n = len(rows)
    sr = sum(float(r["r"]) for r in rows)
    cats = {}
    for cat in ("tp", "sl", "time"):
        sub = [float(r["r"]) for r in rows if r["outcome"] == cat]
        cats[cat] = (len(sub), sum(sub))
    print(f"{label:20s} n={n:4d} SR={sr:+7.1f} | "
          f"tp {cats['tp'][0]:4d}/{cats['tp'][1]:+7.1f} | "
          f"sl {cats['sl'][0]:4d}/{cats['sl'][1]:+7.1f} | "
          f"time {cats['time'][0]:3d}/{cats['time'][1]:+6.1f}")
