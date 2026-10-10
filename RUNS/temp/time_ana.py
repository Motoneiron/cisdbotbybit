"""time_ana.py — вклад tp/sl/time в ΣR по конфигам стэка tf1 (+time по годам)."""
import glob
import os
import pickle
import statistics

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"

MODES = [
    ("tf1sl15sp21_lc", "строка 4 (V+D, как в боте)"),
    ("tf1lc15_foff", "строка 1 (без V и D)"),
    ("tf1lc15_fv", "строка 2 (только V)"),
    ("tf1lc15_fd", "строка 3 (только D)"),
    ("tf1sl15sp21", "справка: лукап cb (V+D)"),
]

for m, label in MODES:
    rows = []
    for f in sorted(glob.glob(os.path.join(BASE, m, "*.pkl"))):
        rows += pickle.load(open(f, "rb"))
    print(f"=== {m} — {label}")
    tot = 0.0
    for cat in ("tp", "sl", "time"):
        sub = [float(r["r"]) for r in rows if r["outcome"] == cat]
        s = sum(sub)
        tot += s
        if sub:
            pos = sum(1 for x in sub if x > 0)
            med = statistics.median(sub)
            print(f"  {cat:4s}: n={len(sub):4d}  SR={s:+7.1f}  avg={s/len(sub):+.3f}  "
                  f"плюсовых={pos} ({pos/len(sub)*100:.0f}%)  медиана={med:+.2f}")
        else:
            print(f"  {cat:4s}: n=0")
    print(f"  ИТОГО SR={tot:+.1f}")
    print()

print("### time по годам:")
for m, label in MODES:
    rows = []
    for f in sorted(glob.glob(os.path.join(BASE, m, "*.pkl"))):
        rows += pickle.load(open(f, "rb"))
    parts = []
    for y in (2024, 2025, 2026):
        sub = [float(r["r"]) for r in rows if r["outcome"] == "time" and str(r["scan"]).startswith(str(y))]
        parts.append(f"{y}: n={len(sub)} SR={sum(sub):+.1f}")
    print(f"  {m:16s} {' | '.join(parts)}")
