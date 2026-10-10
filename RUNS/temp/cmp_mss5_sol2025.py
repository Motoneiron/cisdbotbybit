"""Сравнение SOL-2025: канон (30m-MSS, старый прогон) vs 5m-MSS (A-политика) по классам."""
import pandas as pd

base = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

old = pd.read_pickle(base + "/early_entry_rows_full.pkl")     # старый прогон (30m отбор)
new = pd.read_pickle(base + "/early_entry_mss5_rows.pkl")     # новый (5m отбор)


def show(name, d):
    tp = (d.out == "tp").sum()
    sl = (d.out == "sl").sum()
    wr = 100 * tp / max(1, tp + sl)
    print(f"{name:34s} n={len(d):5d} avg={d.r.mean():+.4f} ΣR={d.r.sum():+8.1f} WR={wr:5.1f}%")


d1 = old[(old.sym == "SOL") & (old.year == 2025)]
d2 = new[(new.sym == "SOL") & (new.year == 2025)]
print("== SOL-2025 ==")
print("OLD (30m-MSS, отбор 30m):")
show("  все", d1)
show("  close_beyond", d1[d1.grp == "close_beyond"])
print("NEW (5m-MSS):")
show("  все", d2)
show("  close_beyond", d2[d2.grp == "close_beyond"])
show("  wick_only", d2[d2.grp == "wick_only"])

# контекст: старый полный набор, close_beyond, только 2025 (все пары)
print("\n== контекст: OLD 30m-MSS, close_beyond, 2025 все пары ==")
d1y = old[(old.year == 2025) & (old.grp == "close_beyond")]
show("  all pairs 2025", d1y)

print("\n== контекст: OLD 30m-MSS, close_beyond, 2024-2026 ==")
d1r = old[(old.year >= 2024) & (old.grp == "close_beyond")]
show("  all pairs 2024-26", d1r)
