# stop_timing_ana3.py — разрез по 4h-границе (конфирм в той же / следующей 4h-свече).
import pandas as pd
import numpy as np

B = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df_alloff_l1h.pkl").copy()
A = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df.pkl").copy()

for df in (B, A):
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["tbt"] = pd.to_datetime(df["tbt"])
    df["d_tc"] = ((df["cbt"].dt.floor("4h") - df["tbt"].dt.floor("4h")).dt.total_seconds() / 14400).round().astype(int)
    df["year"] = df["cbt"].dt.year
    df["fast"] = df["dt_sw"] < 120

print("=== B: d_tc x year (SR / n), всё ===")
t = B.pivot_table(index="year", columns="d_tc", values="r", aggfunc=["sum", "size"])
print(t.round(1).to_string())
print("\n=== B >=2ч: d_tc x year ===")
t = B[np.logical_not(B["fast"])].pivot_table(index="year", columns="d_tc", values="r", aggfunc=["sum", "size"])
print(t.round(1).to_string())
print("\n=== B: d_tc x pair (SR / n), всё ===")
t = B.pivot_table(index="sym", columns="d_tc", values="r", aggfunc=["sum", "size"])
print(t.round(1).to_string())

print("\n=== Матрица (B): fast(<2ч) x cross4h ===")
for f in [True, False]:
    for c in [1, 0]:
        m1 = B["fast"] == f
        m2 = B["d_tc"] == c
        s = B[m1.values * m2.values] if False else B[pd.concat([m1, m2], axis=1).all(axis=1)]
        if len(s):
            print(f"{'<2ч ' if f else '>=2ч':5s} & {'след.свеча' if c==1 else 'та же свеча':10s}: n={len(s):4d} tp={(s['outcome']=='tp').sum():3d} sl={(s['outcome']=='sl').sum():3d} time={(s['outcome']=='time').sum():3d} SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}")

print("\n=== Матрица (A: кандидат) ===")
for f in [True, False]:
    for c in [1, 0]:
        m1 = A["fast"] == f
        m2 = A["d_tc"] == c
        s = A[pd.concat([m1, m2], axis=1).all(axis=1)]
        if len(s):
            print(f"{'<2ч ' if f else '>=2ч':5s} & {'след.свеча' if c==1 else 'та же свеча':10s}: n={len(s):4d} tp={(s['outcome']=='tp').sum():3d} sl={(s['outcome']=='sl').sum():3d} time={(s['outcome']=='time').sum():3d} SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}")

# точный состав d_tc=1 среди <2ч
print("\n=== B: d_tc=1 & <2ч состав ===")
m1 = B["fast"]
m2 = B["d_tc"] == 1
s = B[pd.concat([m1, m2], axis=1).all(axis=1)]
print(f"n={len(s)}, SR={s['r'].sum():+.1f}, исходы={s['outcome'].value_counts().to_dict()}")
