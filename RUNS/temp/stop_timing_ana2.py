# stop_timing_ana2.py — сравнение: A=кандидат (с свип-ATR) vs B=noatr (без свип-ATR), отсечение <2ч.
import os, pickle
import pandas as pd

ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"
A = "stopt_tf1lc15_l1h"        # кандидат (min_sweep_atr=0.40)
B = "stopt_tf1lc15_alloff_l1h" # без свип-ATR (0.0), вход 1ч


def load_all(d):
    rows = []
    for f in sorted(os.listdir(os.path.join(ROOT, d))):
        if f.endswith(".pkl"):
            with open(os.path.join(ROOT, d, f), "rb") as fh:
                rows += pickle.load(fh)
    return rows


def prep(rows):
    df = pd.DataFrame(rows)
    df["cbt"] = pd.to_datetime(df["cbt"])
    df["tbt"] = pd.to_datetime(df["tbt"])
    df["scan"] = pd.to_datetime(df["scan"])
    df["dt_sw"] = (df["cbt"] - df["tbt"]).dt.total_seconds() / 60.0
    df["year"] = df["cbt"].dt.year
    return df


da, db = prep(load_all(A)), prep(load_all(B))
print("A (кандидат, с ATR): n =", len(da), "| B (noatr): n =", len(db))


def rep(name, s):
    n = len(s)
    sr = s["r"].sum()
    sl = (s["outcome"] == "sl").sum()
    tp = (s["outcome"] == "tp").sum()
    tm = (s["outcome"] == "time").sum()
    print(f"{name}: n={n} SR={sr:+.1f} avgR={s['r'].mean():+.3f} | tp={tp} sl={sl} time={tm}")
    for y, g in s.groupby("year"):
        print(f"      {y}: n={len(g):3d} SR={g['r'].sum():+.1f}")


print("\n########## A: кандидат (с ATR 0.40, вход 1ч) ##########")
rep("A все     ", da)
rep("A >=2ч    ", da[da["dt_sw"] >= 120])
print("\n########## B: noatr (без свип-ATR, вход 1ч) ##########")
rep("B все     ", db)
rep("B >=2ч    ", db[db["dt_sw"] >= 120])
rep("B <2ч     ", db[db["dt_sw"] < 120])

print("\n########## Сравнение наборов (ключ sym,dir,scan,cbt) ##########")
ka = set(zip(da.sym, da.direction, da.scan.astype(str), da.cbt.astype(str)))
kb = set(zip(db.sym, db.direction, db.scan.astype(str), db.cbt.astype(str)))
print("общие:", len(ka & kb), "| only-A (пропали у B):", len(ka - kb), "| only-B (новые у B):", len(kb - ka))

ma = {(r.sym, r.direction, str(r.scan), str(r.cbt)): r for r in da.itertuples()}
mb = {(r.sym, r.direction, str(r.scan), str(r.cbt)): r for r in db.itertuples()}
diff = sum(1 for k in (ka & kb) if abs(ma[k].r - mb[k].r) > 1e-9)
print("общие сделки с отличающимся r:", diff)

only_b = kb - ka
mask = [tuple(x) in only_b for x in zip(db.sym, db.direction, db.scan.astype(str), db.cbt.astype(str))]
newb = db[mask]
print(f"\nновые у B (only-B): n={len(newb)} SR={newb['r'].sum():+.1f} avgR={newb['r'].mean():+.3f} исх={newb['outcome'].value_counts().to_dict()}")
print(f"   <2ч: n={len(newb[newb['dt_sw']<120])} SR={newb[newb['dt_sw']<120]['r'].sum():+.1f}")
print(f"   >=2ч: n={len(newb[newb['dt_sw']>=120])} SR={newb[newb['dt_sw']>=120]['r'].sum():+.1f}")

only_a = ka - kb
mask_a = [tuple(x) in only_a for x in zip(da.sym, da.direction, da.scan.astype(str), da.cbt.astype(str))]
gona = da[mask_a]
print(f"\nпропали у B (only-A): n={len(gona)} SR={gona['r'].sum():+.1f} avgR={gona['r'].mean():+.3f} исх={gona['outcome'].value_counts().to_dict()}")

# сохранить B-датасет
db.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df_alloff_l1h.pkl")
print("\nsaved: stopt_df_alloff_l1h.pkl")

# агрегат для сводки: B >=2ч кварталы dt_sw
q = db[db["dt_sw"] >= 120]
print("\nB >=2ч, разбивка по корзинам:")
q = q.copy()
q["cb"] = pd.cut(q["dt_sw"], [120, 180, 240, 300, 360, 420, 480], labels=["2-3ч", "3-4ч", "4-5ч", "5-6ч", "6-7ч", "7-8ч"], right=False)
g = q.groupby("cb", observed=False).agg(n=("r", "size"), sr=("r", "sum"), sl=("outcome", lambda x: (x == "sl").sum()), tp=("outcome", lambda x: (x == "tp").sum()))
g["avgR"] = (g["sr"] / g["n"]).round(3)
print(g.round(1).to_string())
