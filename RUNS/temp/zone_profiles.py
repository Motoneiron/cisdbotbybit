# zone_profiles.py — профили прохождения зоны по классам исходов.
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2_track"
rows = []
for f in sorted(os.listdir(BASE)):
    if f.endswith(".pkl"):
        with open(os.path.join(BASE, f), "rb") as fh:
            rows += pickle.load(fh)
df = pd.DataFrame(rows)

print(f"{'класс':6s} | {'n':>4} | {'заход в зону':>11} | {'до -0.25R':>9} | {'до -0.5R':>8} | {'медиана t(-0.5R),мин':>18} | {'медиана t_дна':>12}")
for oc in ("tp", "sl", "time"):
    g = df[df["outcome"] == oc]
    n = len(g)
    dip = g["dip"].mean() * 100
    d25 = g["t_d25"].notna().mean() * 100
    d50 = g["t_d50"].notna().mean() * 100
    t50 = g["t_d50"].median()
    tmae = g["t_mae"].median()
    print(f"{oc:6s} | {n:>4} | {dip:>10.1f}% | {d25:>8.1f}% | {d50:>7.1f}% | {t50:>18.0f} | {tmae:>12.0f}")

print("\nмакс.просадка (медиана mae):")
for oc in ("tp", "sl", "time"):
    g = df[df["outcome"] == oc]
    print(f"  {oc}: mae p50={g['mae'].median():+.2f} p75={g['mae'].quantile(.75):+.2f}")

# контроль: сколько tp-сделок имели повторные заходы в зону после 1ч/4ч?
# (проверяем по t_dip: он один, поэтому косвенно — по данным BE1: сколько tp закрылись по be)
print("\nдоп: у скольких сделок дно ПОСЛЕ 4ч, по классам:")
for oc in ("tp", "sl", "time"):
    g = df[df["outcome"] == oc]
    print(f"  {oc}: {(g['t_mae'] > 240).mean() * 100:.0f}%")
