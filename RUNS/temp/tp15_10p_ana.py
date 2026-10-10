# tp15_10p_ana.py — сравнение кандидата v2 с TP=1R и TP=1.5R на 10 парах.
import os
import pickle
import pandas as pd

SYMS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC", "XRP", "BTC", "AVAX", "TON"]


def load_dir(root):
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl") and f.split("_")[0] in SYMS:
            with open(os.path.join(root, f), "rb") as fh:
                rows += pickle.load(fh)
    return pd.DataFrame(rows)


R1 = load_dir(r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2")
R15 = load_dir(r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2_tp15")
for df in (R1, R15):
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["year"] = df["cbt"].dt.year


def summ(s):
    n = len(s)
    tp = int((s["outcome"] == "tp").sum())
    sl = int((s["outcome"] == "sl").sum())
    tm = int((s["outcome"] == "time").sum())
    return f"n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={tp / n * 100:5.1f}% SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}"


print("=== 10 пар, TP=1R ===")
print("всего: ", summ(R1))
for y, g in R1.groupby("year"):
    print(f"  {y}:", summ(g))
print("\n=== 10 пар, TP=1.5R ===")
print("всего: ", summ(R15))
for y, g in R15.groupby("year"):
    print(f"  {y}:", summ(g))

print("\n=== ПО ПАРАМ (1R -> 1.5R): SR ===")
t = pd.DataFrame({
    "1R_SR": R1.groupby("sym")["r"].sum().round(1),
    "1.5R_SR": R15.groupby("sym")["r"].sum().round(1),
    "1R_n": R1.groupby("sym")["r"].size(),
    "1.5R_n": R15.groupby("sym")["r"].size(),
})
t["delta"] = (t["1.5R_SR"] - t["1R_SR"]).round(1)
print(t.to_string())


def key(df):
    return list(zip(df["sym"], df["direction"], df["scan"].astype(str), df["cbt"].astype(str)))


R1["k"] = key(R1)
R15["k"] = key(R15)
k1, k15 = set(R1["k"]), set(R15["k"])
common = k1 & k15
print(f"\nключи: общие={len(common)} | только-1R={len(k1 - k15)} | только-1.5R={len(k15 - k1)}")

m1 = R1[R1["k"].isin(k1 - k15)]
m15 = R15[R15["k"].isin(k15 - k1)]
print("только-1R:", summ(m1))
print("только-1.5R:", summ(m15))

# переходы на общих
a = R1.set_index("k")[["outcome", "r"]].rename(columns={"outcome": "o1", "r": "r1"})
b = R15.set_index("k")[["outcome", "r"]].rename(columns={"outcome": "o15", "r": "r15"})
M = a.loc[list(common)].join(b.loc[list(common)])
M["d"] = M["r15"] - M["r1"]
print("\n=== Переходы исходов (общие сделки) ===")
g = M.groupby(["o1", "o15"]).agg(n=("d", "size"), dR=("d", "sum")).round(2)
print(g.to_string())
print("итог dR на общих:", round(M["d"].sum(), 2))
print("общий Δ SR (1.5R - 1R):", round(R15["r"].sum() - R1["r"].sum(), 1))

R15.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_10p_tp15.pkl")
R1.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_10p_tp1.pkl")
print("saved: stopt_v2_10p_tp15.pkl / stopt_v2_10p_tp1.pkl")
