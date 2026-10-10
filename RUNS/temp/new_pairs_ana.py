# new_pairs_ana.py — итоги кандидата v2 на новых парах AVAX/NEAR/UNI/TON.
import os
import pickle
import pandas as pd

ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2"
rows = []
for f in sorted(os.listdir(ROOT)):
    if f.endswith(".pkl") and f.split("_")[0] in ("AVAX", "NEAR", "UNI", "TON"):
        with open(os.path.join(ROOT, f), "rb") as fh:
            rows += pickle.load(fh)
df = pd.DataFrame(rows)
df["cbt"] = pd.to_datetime(df["cbt"])
df["year"] = df["cbt"].dt.year


def summ(s):
    n = len(s)
    if n == 0:
        return "n=0"
    tp = int((s["outcome"] == "tp").sum())
    sl = int((s["outcome"] == "sl").sum())
    tm = int((s["outcome"] == "time").sum())
    return f"n={n:3d} tp={tp:2d} sl={sl:2d} time={tm:2d} WR={tp/n*100:5.1f}% SR={s['r'].sum():+6.1f} avgR={s['r'].mean():+.3f}"


print("ИТОГО новые 4 пары:", summ(df))
print("\nПО ГОДАМ:")
for y, g in df.groupby("year"):
    print(f"  {y}:", summ(g))
print("\nПО ПАРАМ:")
for sym, g in df.groupby("sym"):
    print(f"  {sym:4s}:", summ(g))
    yr = g.groupby("year")["r"].agg(["size", "sum"]).round(1)
    print(f"        по годам: {dict((int(i), (int(r['size']), float(r['sum']))) for i, r in yr.iterrows())}")
print("\nПО НАПРАВЛЕНИЮ:")
for d, g in df.groupby("direction"):
    print(f"  {d:5s}:", summ(g))
df.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_new4.pkl")
print("\nsaved: stopt_v2_new4.pkl")
