"""Быстрый описательный срез реализуемого потока (final_early_trades.pkl) — НЕ вердикт.
Эры: disc=2020-23, val=2024-25, hold=2026. Час — как в данных (naive, UTC-сетка симуляции).
"""
import pickle
from collections import defaultdict

import pandas as pd

with open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/final_early_trades.pkl", "rb") as f:
    obj = pickle.load(f)

df = pd.DataFrame(obj)
df["ts"] = pd.to_datetime(df["ts"])
df["hour"] = df["ts"].dt.hour
df["dow"] = df["ts"].dt.dayofweek
df["era"] = df["year"].map(
    lambda y: "disc(20-23)" if y in ("2020", "2021", "2022", "2023")
    else ("val(24-25)" if y in ("2024", "2025") else "hold(26)")
)


def agg(g):
    decided = g[g.outcome.isin(["tp", "sl"])]
    return pd.Series({
        "n": len(g),
        "WR%": round(100 * (g.outcome == "tp").sum() / max(1, len(decided)), 1),
        "SumR": round(g.r.sum(), 1),
        "AvgR": round(g.r.mean(), 3),
    })


print("=== ПО ЭРАМ ===")
print(df.groupby("era").apply(agg).to_string())
print()

print("=== 4-ЧАСОВЫЕ КОРЗИНЫ (час UTC) ===")
df["hb"] = (df["hour"] // 4 * 4).astype(int)
t = df.groupby(["hb", "era"]).apply(agg).unstack(1)
print(t.to_string())
print()

print("=== ДНИ НЕДЕЛИ (0=Пн) ===")
tt = df.groupby(["dow", "era"]).apply(agg).unstack(1)
print(tt.to_string())
print()

print("=== НАПРАВЛЕНИЕ ===")
print(df.groupby(["dir", "era"]).apply(agg).unstack(1).to_string())
