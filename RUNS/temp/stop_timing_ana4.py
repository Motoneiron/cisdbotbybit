# stop_timing_ana4.py — контроль: d_tc внутри корзин dt_sw; позиция свипа в свече.
import pandas as pd
import numpy as np

B = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_df_alloff_l1h.pkl").copy()
B["cbt"] = pd.to_datetime(B["cbt"])
B["tbt"] = pd.to_datetime(B["tbt"])
B["d_tc"] = ((B["cbt"].dt.floor("4h") - B["tbt"].dt.floor("4h")).dt.total_seconds() / 14400).round().astype(int)
B["pos_t"] = (B["tbt"] - B["tbt"].dt.floor("4h")).dt.total_seconds() / 60  # позиция свипа в своей 4h свече, мин

print("=== Контроль: внутри корзин dt_sw (120+) сравнить d_tc=0 vs 1 ===")
B["cb"] = pd.cut(B["dt_sw"], [120, 180, 240, 300, 360, 480], labels=["2-3ч", "3-4ч", "4-5ч", "5-6ч", "6-8ч"], right=False)
for lab in ["2-3ч", "3-4ч", "4-5ч", "5-6ч", "6-8ч"]:
    s = B[B["cb"] == lab]
    r = []
    for d in [0, 1]:
        g = s[s["d_tc"] == d]
        if len(g) >= 5:
            r.append(f"d{d}: n={len(g):3d} SR={g['r'].sum():+6.1f} avgR={g['r'].mean():+.3f}")
        else:
            r.append(f"d{d}: n={len(g):3d} (мало)")
    print(f"{lab}: " + " | ".join(r))

print("\n=== Позиция свипа в своей 4h-свече (медиана, мин) по d_tc ===")
print(B.groupby("d_tc")["pos_t"].agg(["median", "mean", "size"]).round(1).to_string())

print("\n=== avgR по позиции свипа (кварталы 4h) x d_tc ===")
B["pq"] = pd.cut(B["pos_t"], [0, 60, 120, 180, 240], labels=["q1 0-60", "q2 60-120", "q3 120-180", "q4 180-240"], right=False)
t = B.pivot_table(index="pq", columns="d_tc", values="r", aggfunc=["mean", "size"], observed=False)
print(t.round(3).to_string())

print("\n=== Контроль-2: только >=2ч, короткие корзины 120-150 и 150-180 ===")
s = B[(B["dt_sw"] >= 120) & (B["dt_sw"] < 180)]
for d in [0, 1]:
    g = s[s["d_tc"] == d]
    print(f"dt 2-3ч, d{d}: n={len(g):3d} SR={g['r'].sum():+6.1f} avgR={g['r'].mean():+.3f}")
