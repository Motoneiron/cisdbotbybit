# be_ana2.py — корректный разбор BE-серии на 10 парах кандидата.
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"
SYM10 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC", "XRP", "BTC", "AVAX", "TON"]


def load_dir(name):
    root = os.path.join(BASE, name)
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl") and f.split("_")[0] in SYM10:
            with open(os.path.join(root, f), "rb") as fh:
                rows += pickle.load(fh)
    df = pd.DataFrame(rows)
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["year"] = df["cbt"].dt.year
    return df


def summ(s):
    n = len(s)
    c = s["outcome"].value_counts().to_dict()
    tp, sl, tm, be = c.get("tp", 0), c.get("sl", 0), c.get("time", 0), c.get("be", 0)
    return (n, tp, sl, tm, be, tp / n * 100, s["r"].sum(), s["r"].mean())


base = load_dir("stopt_tf1v2")
nb, tpb, slb, tmb, _, wrb, srb, avb = summ(base)
print(f"БАЗА(10п): n={nb} tp={tpb} sl={slb} time={tmb} WR={wrb:.1f}% SR={srb:+.1f} avgR={avb:+.3f}")

print(f"\n{'N':>3} | {'n':>4} | {'tp':>3} | {'sl':>3} | {'tm':>3} | {'be':>3} | {'WR':>5} | {'SR':>7} | {'Δбаза':>6} | спасено sl->be | убито tp->be")
for nn in (1, 2, 3, 4, 6, 8, 12):
    d = load_dir(f"stopt_tf1v2_be{nn}")
    n, tp, sl, tm, be, wr, sr, av = summ(d)
    print(f"{nn:>3} | {n:>4} | {tp:>3} | {sl:>3} | {tm:>3} | {be:>3} | {wr:>5.1f} | {sr:>+7.1f} | {sr - srb:>+6.1f}")

# годы для ключевых точек
for nn in (4, 6, 12):
    d = load_dir(f"stopt_tf1v2_be{nn}")
    parts = []
    for y, g in d.groupby("year"):
        parts.append(f"{y}: {g['r'].sum():+.1f}/{len(g)}")
    print(f"BE{nn}: " + " · ".join(parts))
print("база: " + " · ".join(f"{y}: {g['r'].sum():+.1f}/{len(g)}" for y, g in base.groupby("year")))

# достижимость: какой r у be-класса
d = load_dir("stopt_tf1v2_be12")
be = d[d["outcome"] == "be"]
print(f"\nbe-класс (BE12): n={len(be)}, спасено из sl={int((be['r'] > -0.9).sum())}, средний r={be['r'].mean():+.3f}")
