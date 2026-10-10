# tp_trans.py — переходы исходов между TP-режимами (SOL/2025, кандидат v2).
import pickle
import pandas as pd


def load(p):
    with open(p, "rb") as f:
        return pd.DataFrame(pickle.load(f))


A = load(r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2\SOL_2025.pkl")
B = load(r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\quick_tp_tf1v2_tp15\SOL_2025.pkl")
C = load(r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\quick_tp_tf1v2_tp20\SOL_2025.pkl")


def key(df):
    return df[["direction", "scan", "cbt"]].astype(str).agg("|".join, axis=1)


for df in (A, B, C):
    df["k"] = key(df)

mA = A[["k", "direction", "scan", "outcome", "r"]].copy()
mB = B[["k", "outcome", "r"]].rename(columns={"outcome": "outcome_15", "r": "r_15"})
mC = C[["k", "outcome", "r"]].rename(columns={"outcome": "outcome_20", "r": "r_20"})
M = mA.merge(mB, on="k").merge(mC, on="k")
print("n =", len(M), "| ключи совпали:", len(M) == len(A) == len(B) == len(C))

M["dR_15"] = M["r_15"] - M["r"]
M["dR_20"] = M["r_20"] - M["r_15"]

print("\n=== Переход 1R -> 1.5R (по парам исходов) ===")
t = M.groupby(["outcome", "outcome_15"]).agg(n=("dR_15", "size"), dR=("dR_15", "sum")).round(2)
print(t.to_string())
print("итог dR_15 =", round(M["dR_15"].sum(), 2))

print("\n=== Переход 1.5R -> 2R ===")
t = M.groupby(["outcome_15", "outcome_20"]).agg(n=("dR_20", "size"), dR=("dR_20", "sum")).round(2)
print(t.to_string())
print("итог dR_20 =", round(M["dR_20"].sum(), 2))

print("\n=== Крупные изменения 1R->1.5R (|dR| >= 0.3) ===")
big = M[abs(M["dR_15"]) >= 0.3].sort_values("dR_15")
for _, row in big.iterrows():
    print(f"{row['direction']:5s} {row['scan'][:16]}  {row['outcome']:4s}->{row['outcome_15']:4s} | r {row['r']:+.2f} -> {row['r_15']:+.2f} (d {row['dR_15']:+.2f})")

print("\n=== Крупные изменения 1.5R->2R (|dR| >= 0.3) ===")
big = M[abs(M["dR_20"]) >= 0.3].sort_values("dR_20")
for _, row in big.iterrows():
    print(f"{row['direction']:5s} {row['scan'][:16]}  {row['outcome_15']:4s}->{row['outcome_20']:4s} | r {row['r_15']:+.2f} -> {row['r_20']:+.2f} (d {row['dR_20']:+.2f})")
