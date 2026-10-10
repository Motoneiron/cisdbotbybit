"""Парсер honest_timeout_all.txt → сводка: пики по парам."""
import re

import pandas as pd

text = open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/honest_timeout_all.txt", encoding="utf-8").read()
blocks = re.split(r"=== ", text)
rows = []
for b in blocks[1:]:
    header = b.split("\n", 1)[0]
    m = re.match(r"([A-Z]+) (tf\d) \(база: vwap\+sp, (\d+) кандидатов\)", header)
    if not m:
        continue
    sym, prof, base = m.group(1), m.group(2), int(m.group(3))
    for line in b.splitlines():
        lm = re.match(r"\s*окно\s+(\d+)м: n=\s*(\d+) потеряно=\s*(\d+) WR=\s*([\d.]+)% SumR=\s*([+-][\d.]+)", line)
        if lm:
            rows.append({"sym": sym, "prof": prof, "x": int(lm.group(1)), "n": int(lm.group(2)),
                         "lost": int(lm.group(3)), "wr": float(lm.group(4)), "r": float(lm.group(5))})
df = pd.DataFrame(rows)
print("Парсено блоков:", df.groupby(["sym", "prof"]).ngroups, "| пар:", df.sym.nunique())
for prof in ("tf7", "tf8"):
    print(f"\n===== {prof}: пик SumR по паре =====")
    for sym in sorted(df[df.prof == prof].sym.unique()):
        d = df[(df.prof == prof) & (df.sym == sym)].sort_values("x")
        if d.empty:
            continue
        best = d.loc[d.r.idxmax()]
        r20 = d[d.x == 20].r.iloc[0] if (d.x == 20).any() else None
        r30 = d[d.x == 30].r.iloc[0] if (d.x == 30).any() else None
        r60 = d[d.x == 60].r.iloc[0] if (d.x == 60).any() else None
        print(f"  {sym:5}: пик {int(best.x):3d}м (SumR {best.r:+.1f}) | 20м: {r20:+.1f} | 30м: {r30:+.1f} | 60м: {r60:+.1f}")

# совокупно (что уже есть в файле)
print("\n===== СОВОКУПНО (по посчитанным) =====")
for prof in ("tf7", "tf8"):
    d = df[df.prof == prof]
    print(f"{prof}:")
    for x in sorted(d.x.unique()):
        dx = d[d.x == x]
        print(f"  {x:3d}м: n={int(dx.n.sum()):5d} SumR={dx.r.sum():+8.1f}")
