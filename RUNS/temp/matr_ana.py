# matr_ana.py — матрица 2x2 (EMA-гейт × dt-фильтр≥2ч), 10 пар, 2024-2026.
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"
SYM10 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC", "XRP", "BTC", "AVAX", "TON"]


def load(name):
    root = os.path.join(BASE, name)
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl") and f.split("_")[0] in SYM10:
            rows += pickle.load(open(os.path.join(root, f), "rb"))
    df = pd.DataFrame(rows)
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["year"] = df["cbt"].dt.year
    return df


def line(nm, d):
    c = d["outcome"].value_counts().to_dict()
    tp, sl, tm = c.get("tp", 0), c.get("sl", 0), c.get("time", 0)
    wr = tp / len(d) * 100 if len(d) else 0
    print(f"{nm:30s} n={len(d):4d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={wr:5.1f}% SR={d['r'].sum():+7.1f} avgR={d['r'].mean():+.3f}")


A = load("stopt_tf1v2")
B = load("stopt_tf1v2_ngate")
C = load("stopt_tf1lc15_alloff_l1h")
print("=== МАТРИЦА 2x2 (10 пар, 2024-2026, TP1R, вход 1ч, поза 16ч) ===")
line("A: гейт + dt (кандидат)", A)
line("B: БЕЗ гейта + dt", B)
line("C: гейт + БЕЗ dt", C)
print()
print(f"Вклад гейта (A-B): {A['r'].sum()-B['r'].sum():+.1f}   |  Вклад dt (A-C): {A['r'].sum()-C['r'].sum():+.1f}")
print()
for nm, d in [("A гейт+dt  ", A), ("B без гейта", B), ("C без dt  ", C)]:
    ys = " · ".join(f"{y}: {g['r'].sum():+.1f}" for y, g in d.groupby("year"))
    print(f"{nm} по годам: {ys}")
try:
    rows = pickle.load(open(os.path.join(BASE, "quick_tp_tf1ng_q/SOL_2025.pkl"), "rb"))
    d = pd.DataFrame(rows)
    d["cbt"] = pd.to_datetime(d["cbt"])
    line("D: без гейта без dt (SOL'25)", d)
except Exception as e:
    print("D err:", e)
