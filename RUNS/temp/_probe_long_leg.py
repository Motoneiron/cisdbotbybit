"""Проверка LONG/SHORT-эффекта на потоке: по парам, исходам, эрам. Не вердикт — фактура."""
import pickle
from collections import Counter

import pandas as pd

with open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/final_early_trades.pkl", "rb") as f:
    obj = pickle.load(f)

df = pd.DataFrame(obj)
df["era"] = df["year"].map(lambda y: "disc" if y in ("2020", "2021", "2022", "2023")
                           else ("val" if y in ("2024", "2025") else "hold"))


def agg(g):
    decided = g[g.outcome.isin(["tp", "sl"])]
    tp = (g.outcome == "tp").sum()
    sl = (g.outcome == "sl").sum()
    tm = (g.outcome == "time").sum()
    return pd.Series({
        "n": len(g), "TP": tp, "SL": sl, "TIME": tm,
        "WR%": round(100 * tp / max(1, tp + sl), 1),
        "SumR": round(g.r.sum(), 1), "AvgR": round(g.r.mean(), 3),
    })


print("=== ПАРА x НАПРАВЛЕНИЕ (вся история) ===")
t = df.groupby(["sym", "dir"]).apply(agg).unstack(0)
# переставлю: строки dir, колонки пары, покажу n/SumR/AvgR
for metric in ("n", "WR%", "SumR", "AvgR"):
    print(f"\n-- {metric} --")
    print(t[metric].to_string())

print("\n=== ИСХОДЫ x НАПРАВЛЕНИЕ (вся история) ===")
print(df.groupby("dir").apply(agg).to_string())

print("\n=== ПАРА x НАПРАВЛЕНИЕ в val(24-25): SumR ===")
v = df[df.era == "val"].groupby(["sym", "dir"]).apply(agg).unstack(0)
print(v["SumR"].to_string())
print("\n-- WR% val --")
print(v["WR%"].to_string())

print("\n=== ГОД x НАПРАВЛЕНИЕ: SumR ===")
y = df.groupby(["year", "dir"]).apply(agg).unstack(0)
print(y["SumR"].to_string())
print("\n-- WR% по годам --")
print(y["WR%"].to_string())
