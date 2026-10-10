# stop_timing_ana5.py — альтернативные варианты отсечения по 4h-границе.
import pandas as pd
import numpy as np

B = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df_alloff_l1h.pkl").copy()
B["cbt"] = pd.to_datetime(B["cbt"])
B["tbt"] = pd.to_datetime(B["tbt"])
B["d_tc"] = ((B["cbt"].dt.floor("4h") - B["tbt"].dt.floor("4h")).dt.total_seconds() / 14400).round().astype(int)
B["fast"] = B["dt_sw"] < 120
B["ph4_cbt"] = (B["cbt"] - B["cbt"].dt.floor("4h")).dt.total_seconds() / 60.0  # позиция конфирма в его свече, мин
B["pos_t"] = (B["tbt"] - B["tbt"].dt.floor("4h")).dt.total_seconds() / 60.0    # позиция свипа в его свече


def rep(name, s):
    n = len(s)
    sl = (s["outcome"] == "sl").sum()
    tp = (s["outcome"] == "tp").sum()
    tm = (s["outcome"] == "time").sum()
    print(f"{name}: n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}")


print("=== Состав класса «<2ч И в след. свече» (55 сд) ===")
s2 = B[B["fast"] & (B["d_tc"] == 1)]
print(f"n={len(s2)} SR={s2['r'].sum():+.1f} исходы={s2['outcome'].value_counts().to_dict()}")
print("dt_sw: med={:.0f} q25={:.0f} q75={:.0f}".format(s2["dt_sw"].median(), s2["dt_sw"].quantile(.25), s2["dt_sw"].quantile(.75)))
print("позиция свипа в свече: med={:.0f} мин; позиция конфирма: med={:.0f} мин".format(s2["pos_t"].median(), s2["ph4_cbt"].median()))
print("по годам:", {int(y): (len(g), round(g["r"].sum(),1)) for y, g in s2.groupby(B["cbt"].dt.year)})
print("по парам:", {k: (len(g), round(g["r"].sum(),1)) for k, g in s2.groupby("sym")})
print("\nпо dt_sw подгруппам:")
for lo, hi in [(0, 45), (45, 90), (90, 120)]:
    g = s2[(s2["dt_sw"] >= lo) & (s2["dt_sw"] < hi)]
    if len(g):
        print(f"  {lo}-{hi}м: n={len(g)} SR={g['r'].sum():+.1f} avgR={g['r'].mean():+.3f}")

print("\n=== Варианты фильтров (B: 1007) ===")
rep("C0: ничего не режем        ", B)
rep("C1: режем ВСЁ <2ч [тек.]   ", B[~B["fast"]])
rep("C2: режем <2ч только d0    ", B[~(B["fast"] & (B["d_tc"] == 0))])
rep("C3: режем всё d0           ", B[B["d_tc"] == 1])
rep("C4: режем всё, кроме >=2ч&d1", B[(~B["fast"]) & (B["d_tc"] == 1)])
rep("Z:  режем d0 & конфирм в первых 2ч свечи", B[(B["d_tc"] == 1) | (B["ph4_cbt"] >= 120)])

print("\n=== По годам: C1 vs C2 ===")
for name, s in [("C1", B[~B["fast"]]), ("C2", B[~(B["fast"] & (B["d_tc"] == 0))])]:
    yr = s.groupby(s["cbt"].dt.year)["r"].agg(["size", "sum"]).round(1)
    print(name, {int(i): (int(r["size"]), r["sum"]) for i, r in yr.iterrows()})
