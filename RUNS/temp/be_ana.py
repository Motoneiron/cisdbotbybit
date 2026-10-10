# be_ana.py — разбор BE-серии (перенос стопа через N часов) vs база.
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"


def load_dir(name):
    root = os.path.join(BASE, name)
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl"):
            with open(os.path.join(root, f), "rb") as fh:
                rows += pickle.load(fh)
    df = pd.DataFrame(rows)
    df["cbt"] = pd.to_datetime(df["cbt"])
    return df


def summ(s):
    n = len(s)
    c = s["outcome"].value_counts().to_dict()
    tp, sl, tm, be = c.get("tp", 0), c.get("sl", 0), c.get("time", 0), c.get("be", 0)
    return f"n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} be={be:3d} WR={tp / n * 100:5.1f}% SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}"


def key(df):
    return list(zip(df["sym"], df["direction"], df["scan"].astype(str), df["cbt"].astype(str)))


base = load_dir("stopt_tf1v2")
base["k"] = key(base)
kb = set(base["k"])
print("БАЗА (16ч, без BE):", summ(base))

for nn in (1, 2, 3, 4, 6, 8, 12):
    d = load_dir(f"stopt_tf1v2_be{nn}")
    d["k"] = key(d)
    kd = set(d["k"])
    print(f"\n=== BE{nn}ч: {summ(d)}")
    be = d[d["outcome"] == "be"]
    if len(be):
        print(f"    be-класс: медиана r={be['r'].median():+.2f} | доля r>-0.2: {(be['r'] > -0.2).mean() * 100:.0f}% | min={be['r'].min():+.2f}")
    common = kb & kd
    a = base[base["k"].isin(common)].drop_duplicates("k").set_index("k")
    b = d[d["k"].isin(common)].drop_duplicates("k").set_index("k")
    j = a[["outcome", "r"]].join(b[["outcome", "r"]], lsuffix="_a", rsuffix="_b")
    j["d"] = j["r_b"] - j["r_a"]
    g = j.groupby(["outcome_a", "outcome_b"]).agg(n=("d", "size"), dR=("d", "sum")).round(1)
    for (oa, ob), row in g.iterrows():
        if abs(row["dR"]) > 0.3:
            print(f"    {oa:4s}->{ob:4s}: n={int(row['n']):3d} dR={row['dR']:+7.1f}")
    ob_ = base[~base["k"].isin(kd)]
    nb_ = d[~d["k"].isin(kb)]
    print(f"    только-база: n={len(ob_)} SR={ob_['r'].sum():+.1f} | только-BE: n={len(nb_)} SR={nb_['r'].sum():+.1f}")
    print(f"    Σ ΔR = {d['r'].sum() - base['r'].sum():+.1f}")
