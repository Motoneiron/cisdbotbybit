"""Честная проверка BE/трейлов (net с комиссиями) + tf2-подробности."""
import glob
import pickle

import numpy as np
import pandas as pd

D = "D:/PYTHON/cisdbotbybit/RUNS/temp"


def load(pattern):
    rows = []
    for f in sorted(glob.glob(pattern)):
        rows.extend(pickle.load(open(f, "rb")))
    return pd.DataFrame(rows)


def add_net(df):
    df = df.copy()
    df["net"] = df["r_1.0"] - np.where(df["out_1.0"] == "tp", df["fee_maker2"], df["fee_mix"])
    return df


other = add_net(load(f"{D}/tp_grid_other/*.pkl"))
canon = add_net(load(f"{D}/tp_grid/*.pkl"))
canon["profile"] = "tf8"
BOT_HOLD = {"tf0": 6, "tf1": 16, "tf2": 24, "tf8": 6}


def net_variant(g, k):
    """net для варианта k (be0.5/be1.0/tr0.5/tr1.0): tp -> maker2, else mix."""
    out = g[f"{k}_out"]
    r = g[f"{k}_r"]
    return r - np.where(out == "tp", g["fee_maker2"], g["fee_mix"])


print("=== BE/ТРЕЙЛЫ: NET (с комиссиями), бот-hold ===")
print(f"{'профиль':<8}{'TP1R':>9}{'BE0.5':>9}{'BE1.0':>9}{'TR0.5':>9}{'TR1.0':>9}")
for prof in ("tf0", "tf1", "tf2", "tf8"):
    src = other if prof != "tf8" else canon
    g = src[(src["profile"] == prof) & (src["hold"] == BOT_HOLD[prof])]
    line = f"{prof:<8}{g['net'].mean():>+9.3f}"
    for k in ("be0.5", "be1.0", "tr0.5", "tr1.0"):
        line += f"{net_variant(g, k).mean():>+9.3f}"
    print(line)

print("\n=== tf2: ПО НАПРАВЛЕНИЮ ===")
t2 = other[(other["profile"] == "tf2") & (other["hold"] == 24)]
for d in ("LONG", "SHORT"):
    g = t2[t2["dir"] == d]
    print(f"  {d}: n={len(g)} WR={100 * (g[g['out_1.0'].isin(['tp', 'sl'])]['out_1.0'] == 'tp').mean():.1f}% "
          f"avg={g['net'].mean():+.4f} Σ={g['net'].sum():+.0f}")

print("\n=== tf2: СТОП-ПОРОГИ ===")
for thr in (1.0, 1.5, 2.0, 2.5):
    g = t2[t2["stop_pct"] >= thr]
    print(f"  >= {thr}%: n={len(g):>5} avg={g['net'].mean():+.4f} Σ={g['net'].sum():+.0f}")

print("\n=== tf2: ПО ПАРАМ ===")
for sym in sorted(t2["sym"].unique()):
    g = t2[t2["sym"] == sym]
    print(f"  {sym:<5}: n={len(g):>5} avg={g['net'].mean():+.4f}")

print("\n=== tf2: ПО ГОДАМ с BE0.5 (net) ===")
for y in sorted(t2["year"].unique()):
    g = t2[t2["year"] == y]
    print(f"  {y}: TP1R {g['net'].mean():+.3f} | BE0.5 {net_variant(g, 'be0.5').mean():+.3f} "
          f"| BE1.0 {net_variant(g, 'be1.0').mean():+.3f}")

print("\n=== tf2: TIME-выходы (распределение r) ===")
tm = t2[t2["out_1.0"] == "time"]
print(f"  n={len(tm)} avg_r={tm['r_1.0'].mean():+.3f} median={tm['r_1.0'].median():+.3f} "
      f"доля r>0: {100 * (tm['r_1.0'] > 0).mean():.0f}%")
print(f"  MFE медиана: {tm['mfe_r'].median():.2f}R | MAE медиана: {tm['mae_r'].median():.2f}R")
