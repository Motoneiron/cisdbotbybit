"""Оценка временного оптимизма бэктеста: entry_bar vs created_bar по всем сделкам кэша."""
import glob
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

for pattern, name in [
    (r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf7_2024*.pkl", "SOL tf7 2024"),
    (r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf8_2024*.pkl", "SOL tf8 2024"),
]:
    f = sorted(glob.glob(pattern))[-1]
    c = pickle.load(open(f, "rb"))
    trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    diffs = [t["entry_bar"] - t["created_bar"] for t in trades]
    s = pd.Series(diffs)
    print(f"=== {name}: {len(trades)} сделок ===")
    print("diff = entry_bar - created_bar:")
    print(s.value_counts().sort_index().to_string())
    print(f"entry_bar < created_bar: {(s < 0).sum()} ({(s < 0).mean()*100:.1f}%)")
    print(f"entry_bar == created_bar: {(s == 0).sum()} ({(s == 0).mean()*100:.1f}%)")
    print(f"entry_bar > created_bar: {(s > 0).sum()} ({(s > 0).mean()*100:.1f}%)")
    print()
