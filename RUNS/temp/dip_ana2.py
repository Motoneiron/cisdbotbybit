# dip_ana2.py — время значимых просадок и их минимумов по классам.
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
n = len(df)


def cum(tcol, mask=None):
    s = df[tcol] if mask is None else df[mask][tcol]
    out = []
    for T in (60, 120, 240, 360, 480, 720):
        out.append(f"{T/60:.0f}ч:{(s <= T).mean()*100:4.0f}%")
    return " ".join(out)


print("=== время достижения −0.25R (от входа) ===")
g = df["t_d25"].dropna()
print(f"n={len(g)} ({len(g)/n*100:.0f}% от базы)")
print(f"  p25={g.quantile(.25):.0f} p50={g.quantile(.5):.0f} p75={g.quantile(.75):.0f} p90={g.quantile(.9):.0f} мин")
print("  накопл. доля ВСЕХ сделок (от базы): " + cum("t_d25"))

print("\n=== время достижения −0.5R ===")
g = df["t_d50"].dropna()
print(f"n={len(g)} ({len(g)/n*100:.0f}% от базы)")
print(f"  p25={g.quantile(.25):.0f} p50={g.quantile(.5):.0f} p75={g.quantile(.75):.0f} p90={g.quantile(.9):.0f} мин")
print("  накопл. доля ВСЕХ сделок (от базы): " + cum("t_d50"))

print("\n=== время МИНИМУМА просадки (t_mae) по классам ===")
for oc in ("tp", "sl", "time"):
    g = df[df["outcome"] == oc]["t_mae"].dropna()
    print(f"  {oc:4s}: p50={g.quantile(.5):.0f} p75={g.quantile(.75):.0f} p90={g.quantile(.9):.0f} мин | накопл. «дно уже сделано»: " + cum("t_mae", df["outcome"] == oc))

print("\n=== tp-класс: распределение глубины (mae) ===")
tp = df[df["outcome"] == "tp"]
for lim in (-0.25, -0.5, -0.75, -0.9):
    m = (tp["mae"] <= lim).mean() * 100
    print(f"  ныряли глубже {lim}R: {m:4.0f}% ({int((tp['mae'] <= lim).sum())} сд)")

print("\n=== sl-класс: успевал ли пройти в плюс до стопа ===")
sl = df[df["outcome"] == "sl"]
for lim in (0.3, 0.5, 0.75):
    m = (sl["mfe"] >= lim).mean() * 100
    print(f"  доходили до +{lim}R до стопа: {m:4.0f}% ({int((sl['mfe'] >= lim).sum())} сд)")

print("\n=== time-класс: минимум и текущий ход ===")
tm = df[df["outcome"] == "time"]
print(f"  mae медиана={tm['mae'].median():+.2f} | mfe медиана={tm['mfe'].median():+.2f}")
