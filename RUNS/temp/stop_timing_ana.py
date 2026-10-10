# stop_timing_ana.py — тайминги стоповых сделок vs tp/time (кандидат tf1lc15_l1h).
# Метрики: dt_sw = cbt - tbt (свип→конфирм, мин); ph1h = от начала часа; ph4h = от начала 4h-свечи; dsc = конфирм→скан.
import os, pickle
import pandas as pd
import numpy as np

OLD = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf\tf1lc15_l1h"
NEW = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1lc15_l1h"


def load_all(root):
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl"):
            with open(os.path.join(root, f), "rb") as fh:
                rows += pickle.load(fh)
    return rows


old = load_all(OLD)
new = load_all(NEW)
print("old n =", len(old), "| new n =", len(new))

ko = {(r["sym"], r["direction"], r["scan"], r["cbt"]) for r in old}
kn = {(r["sym"], r["direction"], r["scan"], r["cbt"]) for r in new}
print("keys only-old:", len(ko - kn), "| only-new:", len(kn - ko))

df = pd.DataFrame(new)
df["cbt"] = pd.to_datetime(df["cbt"])
df["tbt"] = pd.to_datetime(df["tbt"])
df["scan"] = pd.to_datetime(df["scan"])
df["dt_sw"] = (df["cbt"] - df["tbt"]).dt.total_seconds() / 60.0
df.loc[df["tbt"].isna() | (df["tbt"].astype(str) == "NaT"), "dt_sw"] = np.nan
df["ph1h"] = df["cbt"].dt.minute + df["cbt"].dt.second / 60.0
df["ph4h"] = (df["cbt"] - df["cbt"].dt.floor("4h")).dt.total_seconds() / 60.0
df["dsc"] = (df["scan"] - df["cbt"]).dt.total_seconds() / 60.0

print("\n=== Сводка по исходам ===")
print(df.groupby("outcome").agg(n=("r", "size"), SR=("r", "sum"), avgR=("r", "mean")).round(3))

print("\n=== Распределения (sl vs tp vs time) ===")
for oc in ["sl", "tp", "time"]:
    sub = df[df["outcome"] == oc]
    print(f"\n--- {oc}: n={len(sub)}, SR={sub['r'].sum():+.1f} ---")
    for col, name in [("dt_sw", "свип→конфирм, мин"), ("ph1h", "от начала часа, мин"),
                      ("ph4h", "от начала 4h, мин"), ("dsc", "конфирм→скан, мин")]:
        s = sub[col].dropna()
        if not len(s):
            print(f"  {name}: нет данных")
            continue
        print(f"  {name}: mean={s.mean():7.1f}  med={s.median():7.1f}  q25={s.quantile(.25):6.1f}  q75={s.quantile(.75):6.1f}")

# --- корзины ---
def bucket_table(col, bins, labels):
    d = df.dropna(subset=[col]).copy()
    d["b"] = pd.cut(d[col], bins=bins, labels=labels, right=False)
    t = d.pivot_table(index="b", columns="outcome", values="r", aggfunc=["size", "sum"], observed=False)
    n = d.pivot_table(index="b", columns="outcome", values="r", aggfunc="size", observed=False).fillna(0).astype(int)
    sr = d.pivot_table(index="b", columns="outcome", values="r", aggfunc="sum", observed=False).fillna(0)
    tot_n = n.sum(axis=1)
    tot_sr = sr.sum(axis=1)
    wr = (n.get("tp", 0) / tot_n.replace(0, np.nan) * 100).round(1)
    avg = (tot_sr / tot_n.replace(0, np.nan)).round(3)
    out = pd.DataFrame({
        "n": tot_n, "sl": n.get("sl", 0), "tp": n.get("tp", 0), "time": n.get("time", 0),
        "SR": tot_sr.round(1), "WR%": wr, "avgR": avg,
        "SR_sl": sr.get("sl", 0).round(1), "SR_tp": sr.get("tp", 0).round(1),
    })
    print(f"\n=== Корзины: {col} ===")
    print(out.to_string())


bucket_table("dt_sw", [0, 30, 60, 120, 240, 480, 960, 100000],
             ["<30м", "30-60м", "1-2ч", "2-4ч", "4-8ч", "8-16ч", "16ч+"])
bucket_table("ph1h", [0, 10, 20, 30, 40, 50, 60], ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60"])
bucket_table("ph4h", [0, 40, 80, 120, 160, 200, 240], ["0-40", "40-80", "80-120", "120-160", "160-200", "200-240"])

# --- позиция внутри часа × исход, доля sl ---
print("\n=== ph1h: доля sl по 15-мин третям часа ===")
d = df.dropna(subset=["ph1h"]).copy()
d["third"] = pd.cut(d["ph1h"], [0, 15, 30, 45, 60], labels=["0-15", "15-30", "30-45", "45-60"], right=False)
g = d.groupby("third", observed=False).agg(n=("r", "size"), sl=("outcome", lambda x: (x == "sl").sum()),
                                           tp=("outcome", lambda x: (x == "tp").sum()), SR=("r", "sum"))
g["sl%"] = (g["sl"] / g["n"] * 100).round(1)
print(g.to_string())

# --- сохранить расширенный датасет ---
df.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df.pkl")
print("\nsaved: stopt_df.pkl")
