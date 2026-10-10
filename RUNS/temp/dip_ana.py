# dip_ana.py — разбор класса «просадка» по трекинг-прогону (10 пар, кандидат v2).
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
print(f"всего сделок: {n}; колонки: {[c for c in df.columns if c in ('dip','t_dip','t_d25','t_d50','mfe','t_mfe','mae','t_mae')]}")
print(f"с заходом в просадку (dip): {int(df['dip'].sum())} ({df['dip'].mean()*100:.1f}%)")
print(f"глубже −0.25R: {int(df['t_d25'].notna().sum())} ({df['t_d25'].notna().mean()*100:.1f}%) | глубже −0.5R: {int(df['t_d50'].notna().sum())} ({df['t_d50'].notna().mean()*100:.1f}%)")

td = df["t_dip"].dropna()
print("\nвремя ПЕРВОГО захода в зону (мин от входа), среди тех у кого был:")
for q in (25, 50, 75, 90):
    print(f"  p{q} = {td.quantile(q/100):.0f} мин ({td.quantile(q/100)/60:.1f}ч)")
print("\nнакопленная доля ВСЕХ сделок, у которых дип уже случился:")
for T in (30, 60, 120, 240, 480, 720):
    frac = (df["t_dip"] <= T).sum() / n * 100
    print(f"  к {T/60:>4.1f}ч: {frac:5.1f}%")

print("\nПО КЛАССАМ:")
for oc in ("tp", "sl", "time"):
    g = df[df["outcome"] == oc]
    if not len(g):
        continue
    tdg = g["t_dip"].dropna()
    print(f"  {oc:4s}: n={len(g):3d} | доля с дипом={g['dip'].mean()*100:5.1f}% | медиана t_dip={tdg.median() if len(tdg) else float('nan'):.0f} мин | mae медиана={g['mae'].median():+.2f}")

print("\nКЛАСС dip -> tp (сходили в минус и всё же взяли тейк):")
d2t = df[(df["outcome"] == "tp") & (df["dip"])]
ntp = int((df["outcome"] == "tp").sum())
print(f"  n={len(d2t)} = {len(d2t)/ntp*100:.0f}% от всех tp, {len(d2t)/n*100:.1f}% от базы")
print(f"  из них глубже −0.25R: {int(d2t['t_d25'].notna().sum())} | глубже −0.5R: {int(d2t['t_d50'].notna().sum())}")
print(f"  медиана времени первого дипа: {d2t['t_dip'].median():.0f} мин; медиана макс.просадки: {d2t['mae'].median():+.2f}R")
print(f"  p90 времени первого дипа: {d2t['t_dip'].quantile(0.9):.0f} мин")

print("\nКЛАСС dip -> sl (уходили в минус и дошли до стопа):")
d2s = df[(df["outcome"] == "sl") & (df["dip"])]
print(f"  n={len(d2s)} | медиана t_dip={d2s['t_dip'].median():.0f} мин")

print("\ntp-сделки, которые сидели глубже −0.5R (кандидаты на убийство BE):")
tp05 = df[(df["outcome"] == "tp") & (df["t_d50"].notna())]
print(f"  n={len(tp05)} ({len(tp05)/ntp*100:.0f}% от tp) | сумма R={tp05['r'].sum():+.1f}")
