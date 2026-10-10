"""count_tf1_sol.py — SOL ΣR по трём режимам tf1: cb (лукап), lc, cc (честные)."""
import glob
import os
import pickle

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"

for mode in ("tf1sl15sp21", "tf1sl15sp21_lc", "tf1sl15sp21_cc"):
    files = sorted(glob.glob(os.path.join(BASE, mode, "SOL_*.pkl")))
    tot, n, parts = 0.0, 0, []
    for f in files:
        rows = pickle.load(open(f, "rb"))
        s = sum(float(r["r"]) for r in rows)
        tot += s
        n += len(rows)
        year = os.path.basename(f).split("_")[1].split(".")[0]
        parts.append(f"{year}:{s:+.2f}")
    print(f"{mode:16s}  ΣR={tot:+7.2f}  n={n:3d}   {'  '.join(parts)}")
