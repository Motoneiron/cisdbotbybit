# tzb_ana.py — TZB-сетка (стоп в БУ при выходе из зоны после X мин) vs база.
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
    return f"n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} be={be:3d} WR={tp / n * 100:5.1f}% SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}"


def key(df):
    return list(zip(df["sym"], df["direction"], df["scan"].astype(str), df["cbt"].astype(str)))


base = load_dir("stopt_tf1v2")
base["k"] = key(base)
kb = set(base["k"])
b_sr = base["r"].sum()
print(f"БАЗА: {summ(base)}")

for tz in (90, 120, 180):
    d = load_dir(f"stopt_tf1v2_tzb{tz}")
    d["k"] = key(d)
    kd = set(d["k"])
    print(f"\n=== TZB{tz}: {summ(d)}  (Δ к базе {d['r'].sum() - b_sr:+.1f})")
    be = d[d["outcome"] == "be"]
    if len(be):
        print(f"    be-класс n={len(be)}: медиана r={be['r'].median():+.2f}, avg={be['r'].mean():+.3f}, мин={be['r'].min():+.2f} | доля r>-0.2: {(be['r'] > -0.2).mean() * 100:.0f}%")
    common = kb & kd
    a = base[base["k"].isin(common)].drop_duplicates("k").set_index("k")
    b = d[d["k"].isin(common)].drop_duplicates("k").set_index("k")
    j = a[["outcome", "r"]].join(b[["outcome", "r"]], lsuffix="_a", rsuffix="_b")
    j["d"] = j["r_b"] - j["r_a"]
    g = j.groupby(["outcome_a", "outcome_b"]).agg(n=("d", "size"), dR=("d", "sum")).round(1)
    for (oa, ob), row in g.iterrows():
        if abs(row["dR"]) > 0.3:
            print(f"    {oa:4s}->{ob:4s}: n={int(row['n']):3d} dR={row['dR']:+7.1f}")
    on_b = base[~base["k"].isin(kd)]
    nn_b = d[~d["k"].isin(kb)]
    print(f"    только-база: n={len(on_b)} SR={on_b['r'].sum():+.1f} | только-TZB: n={len(nn_b)} SR={nn_b['r'].sum():+.1f}")
for tz in (90, 120, 180):
    d = load_dir(f"stopt_tf1v2_tzb{tz}")
    parts = [f"{y}: {g['r'].sum():+.1f}" for y, g in d.groupby("year")]
    print(f"TZB{tz} по годам: " + " · ".join(parts))
print("база по годам: " + " · ".join(f"{y}: {g['r'].sum():+.1f}" for y, g in base.groupby("year")))
