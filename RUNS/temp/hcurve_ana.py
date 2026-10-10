# hcurve_ana.py — полный разбор кривой выходов 2..18ч (кандидат v2, вход 1ч).
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"
HS = [2, 4, 6, 8, 10, 12, 14, 16, 18]


def load_dir(h):
    root = os.path.join(BASE, f"stopt_tf1v2_h{h}")
    if not os.path.isdir(root):
        return None
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl"):
            with open(os.path.join(root, f), "rb") as fh:
                rows += pickle.load(fh)
    df = pd.DataFrame(rows)
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["year"] = df["cbt"].dt.year
    return df


def summ(s):
    n = len(s)
    if n == 0:
        return "n=0"
    tp = int((s["outcome"] == "tp").sum())
    sl = int((s["outcome"] == "sl").sum())
    tm = int((s["outcome"] == "time").sum())
    return f"n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={tp / n * 100:5.1f}% SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}"


def key(df):
    return list(zip(df["sym"], df["direction"], df["scan"].astype(str), df["cbt"].astype(str)))


data = {}
for h in HS:
    d = load_dir(h)
    if d is not None and len(d):
        data[h] = d

print("=== КРИВАЯ (выход 2..18ч) ===")
for h in HS:
    if h in data:
        print(f"h{h:>2}:", summ(data[h]))

print("\n=== ПО ГОДАМ ===")
for h in [2, 6, 10, 14, 18]:
    if h not in data:
        continue
    parts = []
    for y, g in data[h].groupby("year"):
        parts.append(f"{y}: {g['r'].sum():+.1f}/{len(g)}")
    print(f"h{h:>2}: " + " · ".join(parts))

print("\n=== ПЕРЕХОДЫ МЕЖДУ СОСЕДНИМИ ТОЧКАМИ ===")
for ha, hb in zip(HS, HS[1:]):
    if ha not in data or hb not in data:
        continue
    a = data[ha].copy()
    b = data[hb].copy()
    a["k"] = key(a)
    b["k"] = key(b)
    ka, kb = set(a["k"]), set(b["k"])
    common = ka & kb
    a2 = a[a["k"].isin(common)].drop_duplicates("k").set_index("k")
    b2 = b[b["k"].isin(common)].drop_duplicates("k").set_index("k")
    j = a2[["outcome", "r"]].join(b2[["outcome", "r"]], lsuffix="_a", rsuffix="_b")
    j["d"] = j["r_b"] - j["r_a"]
    g = j.groupby(["outcome_a", "outcome_b"]).agg(n=("d", "size"), dR=("d", "sum")).round(2)
    only_a = a[~a["k"].isin(kb)]
    only_b = b[~b["k"].isin(ka)]
    print(f"\n{ha}ч -> {hb}ч: общих={len(common)}, ΔΣR={b['r'].sum() - a['r'].sum():+.1f}")
    for (oa, ob), row in g.iterrows():
        if abs(row["dR"]) > 0.3 or int(row["n"]) > 20:
            print(f"   {oa:4s}->{ob:4s}: n={int(row['n']):3d} dR={row['dR']:+7.1f}")
    print(f"   только-{ha}ч: n={len(only_a)} SR={only_a['r'].sum():+.1f} | только-{hb}ч: n={len(only_b)} SR={only_b['r'].sum():+.1f}")
