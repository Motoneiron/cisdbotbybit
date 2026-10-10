"""Полное сравнение: канон 30m-MSS (oldfull) vs 5m-MSS (mss5) по всем парам/годам."""
import pandas as pd

base = "D:/PYTHON/cisdbotbybit/RUNS/temp"
old = pd.read_pickle(base + "/early_entry_rows_full.pkl")
new = pd.read_pickle(base + "/early_entry_mss5_rows.pkl")

lines = []


def p(s=""):
    print(s, flush=True)
    lines.append(s)


def agg(d, col="r"):
    try:
        if not len(d):
            return "—"
        o = d.out if col == "r" else d.out_inv
        tp = int((o == "tp").sum())
        sl = int((o == "sl").sum())
        return f"n={len(d):5d} avg={d[col].mean():+.4f} ΣR={d[col].sum():+8.1f} WR={100*tp/max(1,tp+sl):4.1f}%"
    except Exception as e:
        return f"err {e}"


p("=" * 100)
p("# СРАВНЕНИЕ: канон 30m-MSS (филл cbt+30) vs 5m-MSS (филл cbt+5)")
p(f"\nвсего: канон n={len(old)}, 5m n={len(new)}")

p("\n## по годам")
for y in sorted(new.year.unique()):
    o = old[old.year == y]
    n = new[new.year == y]
    a = n[n.grp == "close_beyond"]
    w = n[n.grp == "wick_only"]
    p(f"\n{y}:")
    p(f"  канон 30m:      {agg(o)}")
    p(f"  5m все:         {agg(n)}")
    p(f"  5m close_beyond:{agg(a)}")
    p(f"  5m wick A:      {agg(w)}")
    p(f"  5m wick B(inv): {agg(w, 'r_inv')}")

for lbl, yrs in (("2020-2023", range(2020, 2024)), ("2024-2026", range(2024, 2027))):
    o = old[old.year.isin(yrs)]
    n = new[new.year.isin(yrs)]
    a = n[n.grp == "close_beyond"]
    w = n[n.grp == "wick_only"]
    p(f"\n== {lbl} ==")
    p(f"  канон 30m:      {agg(o)}")
    p(f"  5m все:         {agg(n)}")
    p(f"  5m close_beyond:{agg(a)}")
    p(f"  5m wick A:      {agg(w)}")
    p(f"  5m wick B(inv): {agg(w, 'r_inv')}")

p("\n## по парам (все годы): канон | 5m close_beyond | 5m wick")
for s in sorted(new.sym.unique()):
    o = old[old.sym == s]
    n = new[new.sym == s]
    a = n[n.grp == "close_beyond"]
    w = n[n.grp == "wick_only"]
    p(f"\n{s}:")
    p(f"  канон {agg(o)}")
    p(f"  cb    {agg(a)}")
    p(f"  wk    {agg(w)}")

open(base + "/COMPARE_MSS5.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\nзаписано в COMPARE_MSS5.md")
