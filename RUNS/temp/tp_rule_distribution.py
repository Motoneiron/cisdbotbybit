"""Какая формула TP в tf8-потоке бэктеста (filters_off_full)?
R-множитель TP = |entry - tp| / |entry - stop| по каждой сделке.
"""
import glob
import pickle
from collections import Counter

import pandas as pd

rows = []
for f in sorted(glob.glob("D:/PYTHON/CISDBOT/RUNS/filters_off_full/*tf8*.pkl")):
    c = pickle.load(open(f, "rb"))
    sym = c.get("symbol")
    for t in c.get("trades") or []:
        e, s, tp = t.get("entry_px"), t.get("stop"), t.get("tp")
        if not e or not s or not tp:
            continue
        risk = abs(float(e) - float(s))
        if risk <= 0:
            continue
        rows.append((sym, t.get("direction"), abs(float(e) - float(tp)) / risk,
                     str(t.get("htf_time"))[:7]))

df = pd.DataFrame(rows, columns=["sym", "dir", "tp_r", "ym"])
print(f"сделок с TP: {len(df)}")
print()
print("--- R-множитель TP: распределение ---")
bins = [0, 0.6, 0.85, 1.05, 1.3, 1.6, 2.0, 2.4, 2.8, 3.2, 99]
labels = ["<0.6", "0.6-0.85", "≈1R (0.85-1.05)", "1.05-1.3", "1.3-1.6", "1.6-2.0",
          "2.0-2.4", "2.4-2.8", "2.8-3.2", ">3.2"]
cut = pd.cut(df["tp_r"], bins=bins, labels=labels, right=False)
vc = cut.value_counts().reindex(labels)
for k, v in vc.items():
    print(f"  {k:18s}: {v:6d}  ({100 * v / len(df):5.1f}%)")
print()
near1 = ((df.tp_r > 0.85) & (df.tp_r < 1.05)).mean()
print(f"доля строго 1R (0.85-1.05): {100 * near1:.1f}%")
print(f"медиана R-множителя TP: {df.tp_r.median():.3f} | среднее: {df.tp_r.mean():.3f}")
print()
print("--- доля 1R по годам ---")
df["year"] = df["ym"].str[:4]
g = df.groupby("year")["tp_r"].apply(lambda s: 100 * ((s > 0.85) & (s < 1.05)).mean())
cnt = df.groupby("year").size()
for y in sorted(g.index):
    print(f"  {y}: 1R {g[y]:5.1f}%  | сделок {cnt[y]}")
print()
print("--- по парам ---")
g2 = df.groupby("sym")["tp_r"].apply(lambda s: 100 * ((s > 0.85) & (s < 1.05)).mean())
for s in sorted(g2.index):
    print(f"  {s:5s}: 1R {g2[s]:5.1f}%")
