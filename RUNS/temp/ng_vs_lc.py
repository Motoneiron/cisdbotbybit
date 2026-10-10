"""ng_vs_lc.py — сравнение «без якоря» (ng) vs «честный lc» по 8 точкам сеток."""
import glob
import os
import pickle

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"
PAIRS = [
    ("база 5ч/16ч", "tf1ng15_foff", "tf1lc15_foff"),
    ("выход 12ч", "tf1ng15_foff_h12", "tf1lc15_foff_h12"),
    ("выход 8ч", "tf1ng15_foff_h8", "tf1lc15_foff_h8"),
    ("выход 6ч", "tf1ng15_foff_h6", "tf1lc15_foff_h6"),
    ("вход 2ч", "tf1ng15_l2h", "tf1lc15_l2h"),
    ("вход 1ч", "tf1ng15_l1h", "tf1lc15_l1h"),
    ("вход 30м", "tf1ng15_l30m", "tf1lc15_l30m"),
    ("вход 15м", "tf1ng15_l15m", "tf1lc15_l15m"),
]


def load(m):
    rows = []
    for f in sorted(glob.glob(os.path.join(BASE, m, "*.pkl"))):
        rows += pickle.load(open(f, "rb"))
    return rows


def summ(rows):
    n = len(rows)
    sr = sum(float(r["r"]) for r in rows)
    years = {}
    for y in (2024, 2025, 2026):
        years[y] = sum(float(r["r"]) for r in rows if str(r["scan"]).startswith(str(y)))
    tp = sum(1 for r in rows if r["outcome"] == "tp")
    sl = sum(1 for r in rows if r["outcome"] == "sl")
    tm = sum(1 for r in rows if r["outcome"] == "time")
    return n, sr, years, (tp, sl, tm)


for label, mng, mlc in PAIRS:
    n1, s1, y1, c1 = summ(load(mng))
    n2, s2, y2, c2 = summ(load(mlc))
    print(f"### {label}")
    print(f"  ng: n={n1:4d} SR={s1:+7.1f}  (годы {y1[2024]:+6.1f} / {y1[2025]:+6.1f} / {y1[2026]:+6.1f})  tp/sl/time={c1[0]}/{c1[1]}/{c1[2]}")
    print(f"  lc: n={n2:4d} SR={s2:+7.1f}  (годы {y2[2024]:+6.1f} / {y2[2025]:+6.1f} / {y2[2026]:+6.1f})")
    print(f"  ΔSR (ng-lc) = {s1 - s2:+.1f}   Δn = {n1 - n2:+d}")
    print()
