"""Сводка TP1R по tf0/tf1/tf2 (+tf8-канон для сравнения).

Читает tp_grid_other/*.pkl (tf0/tf1/tf2) и tp_grid/*.pkl (tf8-канон).
TP1R: net = r_1.0 - fee; WR среди tp/sl. Бот-hold по профилю: tf0=6, tf1=16, tf2=24.
"""
import glob
import pickle

import numpy as np
import pandas as pd

D = "D:/PYTHON/cisdbotbybit/RUNS/temp"
BOT_HOLD = {"tf0": 6, "tf1": 16, "tf2": 24, "tf8": 6}


def load(pattern):
    rows = []
    for f in sorted(glob.glob(pattern)):
        rows.extend(pickle.load(open(f, "rb")))
    return pd.DataFrame(rows)


def add_net(df):
    df = df.copy()
    df["net"] = df["r_1.0"] - np.where(df["out_1.0"] == "tp", df["fee_maker2"], df["fee_mix"])
    return df


def wr_avg(g):
    w = g[g["out_1.0"].isin(["tp", "sl"])]
    wr = 100 * (w["out_1.0"] == "tp").mean() if len(w) else float("nan")
    return wr


other = add_net(load(f"{D}/tp_grid_other/*.pkl"))
other["family"] = other["profile"]
canon = add_net(load(f"{D}/tp_grid/*.pkl"))
canon["profile"] = "tf8"
canon["family"] = "tf8"

print("=== ГЛАВНАЯ ТАБЛИЦА: TP1R, бот-hold ===")
print(f"{'профиль':<8}{'hold':>5}{'n':>7}{'WR':>7}{'avg':>9}{'ΣR':>9}  {'TP/SL/TIME %':>14}")
for prof in ("tf0", "tf1", "tf2", "tf8"):
    src = other if prof != "tf8" else canon
    hold = BOT_HOLD[prof]
    g = src[(src["profile"] == prof) & (src["hold"] == hold)]
    if g.empty:
        continue
    n = len(g)
    tp = (g["out_1.0"] == "tp").mean() * 100
    sl = (g["out_1.0"] == "sl").mean() * 100
    tm = (g["out_1.0"] == "time").mean() * 100
    print(f"{prof:<8}{hold:>5}{n:>7}{wr_avg(g):>7.1f}{g['net'].mean():>+9.4f}{g['net'].sum():>+9.0f}  "
          f"{tp:>4.0f}/{sl:>3.0f}/{tm:>3.0f}")

print("\n=== ПО ГОДАМ (avg net, бот-hold) ===")
years = sorted(other["year"].unique())
print(f"{'год':<6}" + "".join(f"{p:>9}" for p in ("tf0", "tf1", "tf2", "tf8")))
for y in years:
    line = f"{y:<6}"
    for prof in ("tf0", "tf1", "tf2", "tf8"):
        src = other if prof != "tf8" else canon
        g = src[(src["profile"] == prof) & (src["hold"] == BOT_HOLD[prof]) & (src["year"] == y)]
        line += f"{g['net'].mean():>+9.3f}" if len(g) else f"{'—':>9}"
    print(line)

print("\n=== СЕТКА TP (avg net, бот-hold) ===")
print(f"{'профиль':<8}" + "".join(f"{'TP=' + str(t):>9}" for t in (1.0, 1.25, 1.5, 2.0, 3.0)))
for prof in ("tf0", "tf1", "tf2", "tf8"):
    src = other if prof != "tf8" else canon
    g = src[(src["profile"] == prof) & (src["hold"] == BOT_HOLD[prof])]
    line = f"{prof:<8}"
    for t in (1.0, 1.25, 1.5, 2.0, 3.0):
        net = g[f"r_{t}"] - np.where(g[f"out_{t}"] == "tp", g["fee_maker2"], g["fee_mix"])
        line += f"{net.mean():>+9.3f}"
    print(line)

print("\n=== ВЫХОДЫ-ВАРИАНТЫ (avg net, бот-hold) ===")
print(f"{'профиль':<8}{'TP1R':>9}{'BE0.5':>9}{'BE1.0':>9}{'TR0.5':>9}{'TR1.0':>9}")
for prof in ("tf0", "tf1", "tf2", "tf8"):
    src = other if prof != "tf8" else canon
    g = src[(src["profile"] == prof) & (src["hold"] == BOT_HOLD[prof])]
    line = f"{prof:<8}"
    d = g["r_1.0"] - np.where(g["out_1.0"] == "tp", g["fee_maker2"], g["fee_mix"])
    line += f"{d.mean():>+9.3f}"
    for k in ("be0.5", "be1.0", "tr0.5", "tr1.0"):
        line += f"{g[k + '_r'].mean():>+9.3f}"
    print(line)

print("\n=== РАЗМЕР СТОПА (медиана %, бот-hold) ===")
for prof in ("tf0", "tf1", "tf2", "tf8"):
    src = other if prof != "tf8" else canon
    g = src[(src["profile"] == prof) & (src["hold"] == BOT_HOLD[prof])]
    short = g[g["stop_pct"] < 1.0]["net"].mean()
    wide = g[g["stop_pct"] >= 1.0]["net"].mean()
    print(f"  {prof}: med={g['stop_pct'].median():.2f}% | <1%: {short:+.3f} (n={int((g['stop_pct'] < 1).sum())}) | "
          f">=1%: {wide:+.3f} (n={int((g['stop_pct'] >= 1).sum())})")
