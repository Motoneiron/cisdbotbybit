"""Эллиотт-правило «гонка» (same_leg & откат<0.236): воспроизведение и freeze-check.
Плюс CVD-часть: сверим с отчётом соседей."""
import numpy as np
import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_multi_cvd.pkl")
print("колонки zz:", df.zz_frac.notna().sum(), "из", len(df), "| zz_last_dir:", df.zz_last_dir.notna().sum())

d = df[df.zz_frac.notna()].copy()
leg_dir = np.where(d.zz_last_dir == 1, "LONG", "SHORT")  # up-нога → LONG-сетапы гонят
same_leg = (d["dir"] == leg_dir)
d["chase"] = same_leg & (d.zz_frac < 0.236)

print("\n=== воспроизведение (весь поток с фичей) ===")
ch = d[d.chase]
print(f"gonka-сделки: n={len(ch)} ({(len(ch)/len(d)):.1%}), WR={100*(ch[ch.outcome.isin(['tp','sl'])].outcome=='tp').mean():.1f}%, "
      f"ΣR={ch.r_net.sum():+.1f}, AvgR={ch.r_net.mean():+.3f}")

print("\n=== по годам: gonka-группа ===")
print(f"{'год':>5} | {'n':>4} | {'ΣR':>8} | {'AvgR':>7} | {'WR':>5}")
for y in sorted(d.year.unique()):
    g = d[(d.year == y) & d.chase]
    if not len(g):
        print(f"{y:>5} | 0")
        continue
    w = g[g.outcome.isin(["tp", "sl"])]
    wr = 100 * (w.outcome == "tp").mean() if len(w) else 0
    print(f"{y:>5} | {len(g):>4} | {g.r_net.sum():>+8.1f} | {g.r_net.mean():>+7.3f} | {wr:>4.0f}%")

print("\n=== эффект правила: поток с/без gonka ===")
r_all = d.r_net.sum()
r_keep = d[~d.chase].r_net.sum()
print(f"с gonka: ΣR {r_all:+.0f} | без gonka: ΣR {r_keep:+.0f} | дельта {r_keep - r_all:+.0f}")

print("\n=== по годам: дельта ===")
for y in sorted(d.year.unique()):
    g = d[d.year == y]
    dep = -g[g.chase].r_net.sum()
    print(f"{y}: {dep:+.0f}R")

# frozen-пороги отката: где именно минус
print("\n=== бакеты по frac (same_leg только) ===")
s = d[same_leg].copy()
s["b"] = pd.cut(s.zz_frac, [0, 0.12, 0.236, 0.382, 0.5, 1.0, 100])
for b, g in s.groupby("b", observed=True):
    wr = 100 * (g[g.outcome.isin(["tp","sl"])].outcome == "tp").mean()
    print(f"  {str(b):>14}: n={len(g):>4} WR={wr:>4.0f}% ΣR={g.r_net.sum():>+7.1f} AvgR={g.r_net.mean():+.3f}")
