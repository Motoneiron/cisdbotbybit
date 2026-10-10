"""Прогон 18-го на живом векторе: два варианта.

A) knn18_live_feat — фичи пересчитаны на from_ts, но «момент решения» для зрелости соседей =
   старый decision_at (изолируем эффект пересчёта фич).
B) knn18_live_full — фичи на from_ts И момент решения = from_ts (полный лайв-режим).
"""
import subprocess
import sys

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
src = pd.read_pickle(f"{BASE}/knn18_live_input.pkl")

# A) как есть
src.to_pickle(f"{BASE}/knn18_live_feat_input.pkl")
# B) момент решения = from_ts (лайв)
b = src.copy()
b["decision_at"] = pd.to_datetime(b["from_ts"])
b.to_pickle(f"{BASE}/knn18_live_full_input.pkl")
print("inputs ready", flush=True)

for tag, f in (("live_feat", "knn18_live_feat_input.pkl"), ("live_full", "knn18_live_full_input.pkl")):
    print(f"\n########## {tag} ##########", flush=True)
    r = subprocess.run([sys.executable, f"{BASE}/_knn18_v1.py", f"{BASE}/{f}", "--tag", tag],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-4000:], flush=True)
    if r.returncode != 0:
        print("STDERR:", r.stderr[-2000:], flush=True)
print("\nDONE", flush=True)
