# stop_timing_summary.py — итоговая сводка по вариантам кандидата: n, tp/sl/time, ΣR по годам.
import pandas as pd

A = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df.pkl")             # кандидат (с ATR)
B = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df_alloff_l1h.pkl")  # без ATR

for df in (A, B):
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["tbt"] = pd.to_datetime(df["tbt"])
    df["year"] = df["cbt"].dt.year
    df["d_tc"] = ((df["cbt"].dt.floor("4h") - df["tbt"].dt.floor("4h")).dt.total_seconds() / 14400).round().astype(int)

V = [
    ("V1 кандидат (с ATR, без отсеч.)", A),
    ("V2 кандидат + >=2ч", A[A["dt_sw"] >= 120]),
    ("V3 без ATR (всё)", B),
    ("V4 без ATR + >=2ч", B[B["dt_sw"] >= 120]),
    ("V5 без ATR + >=2ч + след.свеча", B[(B["dt_sw"] >= 120) & (B["d_tc"] == 1)]),
]


def line(name, s):
    n = len(s)
    tp = (s["outcome"] == "tp").sum()
    sl = (s["outcome"] == "sl").sum()
    tm = (s["outcome"] == "time").sum()
    print(f"{name}: n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}")
    for y, g in s.groupby("year"):
        tp = (g["outcome"] == "tp").sum()
        sl = (g["outcome"] == "sl").sum()
        tm = (g["outcome"] == "time").sum()
        wr = tp / len(g) * 100
        print(f"   {y}: n={len(g):3d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={wr:4.1f}% SR={g['r'].sum():+6.1f} avgR={g['r'].mean():+.3f}")


for name, s in V:
    line(name, s)
    print()
