# stop_v2_ana.py — итоговая сводка кандидата v2 (tf1v2) на 10 парах.
import os
import pickle
import pandas as pd

ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2"
rows = []
for f in sorted(os.listdir(ROOT)):
    if f.endswith(".pkl"):
        with open(os.path.join(ROOT, f), "rb") as fh:
            rows += pickle.load(fh)
df = pd.DataFrame(rows)
df["cbt"] = pd.to_datetime(df["cbt"])
df["tbt"] = pd.to_datetime(df["tbt"])
df["year"] = df["cbt"].dt.year
df["dt_sw"] = (df["cbt"] - df["tbt"]).dt.total_seconds() / 60.0


def summ(s):
    n = len(s)
    tp = int((s["outcome"] == "tp").sum())
    sl = int((s["outcome"] == "sl").sum())
    tm = int((s["outcome"] == "time").sum())
    wr = tp / n * 100 if n else 0.0
    return f"n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={wr:5.1f}% SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}"


print("ИТОГО 10 пар:", summ(df))
print("\nПО ГОДАМ:")
for y, g in df.groupby("year"):
    print(f"  {y}:", summ(g))
print("\nПО ПАРАМ:")
for sym, g in df.groupby("sym"):
    print(f"  {sym:5s}:", summ(g))
print("\nПО НАПРАВЛЕНИЮ:")
for d, g in df.groupby("direction"):
    print(f"  {d:5s}:", summ(g))

old6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]
print("\n6 старых пар:", summ(df[df["sym"].isin(old6)]))
print("4 новых пары:", summ(df[~df["sym"].isin(old6)]))

print("\ndt_sw: min={:.0f} med={:.0f} max={:.0f}".format(df["dt_sw"].min(), df["dt_sw"].median(), df["dt_sw"].max()))
print("сделок/день (974д): {:.2f}".format(len(df) / 974))
df.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_10par.pkl")
print("saved: stopt_v2_10par.pkl")
