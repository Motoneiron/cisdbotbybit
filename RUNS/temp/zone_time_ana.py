# zone_time_ana.py — время нахождения в зоне вход–стоп: tp vs sl vs time.
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2_zone"
rows = []
for f in sorted(os.listdir(BASE)):
    if f.endswith(".pkl"):
        with open(os.path.join(BASE, f), "rb") as fh:
            rows += pickle.load(fh)
df = pd.DataFrame(rows)
n = len(df)
print(f"всего: {n}")


def q(g, col, ps=(25, 50, 75, 90)):
    return " ".join(f"p{p}={g[col].quantile(p / 100):.0f}" for p in ps)


print("\n=== ВРЕМЯ В ЗОНЕ (суммарно, мин) по классам ===")
for oc in ("tp", "sl", "time"):
    g = df[df["outcome"] == oc]
    print(f"  {oc:4s} n={len(g):3d} | time_below: {q(g, 'time_below')} | медиана {g['time_below'].median():.0f} мин ({g['time_below'].median() / 60:.1f}ч)")
    print(f"        n_dips: медиана {g['n_dips'].median():.0f}, среднее {g['n_dips'].mean():.1f} | t_last_below: p50={g['t_last_below'].median():.0f}, p90={g['t_last_below'].quantile(.9):.0f} мин")
    print(f"        t_up_first: p50={g['t_up_first'].median():.0f} | t_exit: p50={g['t_exit'].median():.0f} мин")

print("\n=== РАСПРЕДЕЛЕНИЕ по суммарному времени в зоне ===")
bins = [-1, 30, 60, 120, 240, 480, 10000]
labels = ["<30м", "30м-1ч", "1-2ч", "2-4ч", "4-8ч", ">8ч"]
df["zb"] = pd.cut(df["time_below"], bins=bins, labels=labels)
t = df.groupby("zb", observed=True).apply(
    lambda g: pd.Series({
        "n": len(g),
        "доля": f"{len(g) / n * 100:.1f}%",
        "tp%": f"{(g['outcome'] == 'tp').mean() * 100:.0f}%",
        "sl%": f"{(g['outcome'] == 'sl').mean() * 100:.0f}%",
        "time%": f"{(g['outcome'] == 'time').mean() * 100:.0f}%",
        "SR": round(g['r'].sum(), 1),
    })
)
print(t.to_string())

print("\n=== TP-сделки: путь 'после выхода из зоны' ===")
tp = df[df["outcome"] == "tp"]
print(f"  медиана времени в зоне: {tp['time_below'].median():.0f} мин")
print(f"  медиана t_last_below (окончательный выход): {tp['t_last_below'].median():.0f} мин")
print(f"  медиана 'остаток до тэйка' (t_exit - t_last_below): {(tp['t_exit'] - tp['t_last_below']).median():.0f} мин")
print(f"  доля tp, у кого t_last_below ПОСЛЕ 8ч: {(tp['t_last_below'] > 480).mean() * 100:.0f}%")

print("\n=== SL-сделки ===")
sl = df[df["outcome"] == "sl"]
print(f"  медиана времени в зоне: {sl['time_below'].median():.0f} мин")
print(f"  медиана t_last_below: {sl['t_last_below'].median():.0f} мин (≈ момент стопа)")
print(f"  медиана t_exit: {sl['t_exit'].median():.0f} мин")

df.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_zone.pkl")
print("\nsaved: stopt_v2_zone.pkl")
