# -*- coding: utf-8 -*-
"""Уточняющий срез: гейт-прошедшие — 4-pass vs отсечённые прочими, по карте."""
import numpy as np
import pandas as pd

CSV = r"D:\PYTHON\cisdbotbybit\RUNS\cache\nofilter_summary.csv"
df = pd.read_csv(CSV)
df["taken"] = df["taken"].astype(bool)
df["q"] = np.where(df["taken"], df["r"], df["r_cf"])
df["year"] = df["scan"].astype(str).str[:4]

def rb(v):
    if pd.isna(v): return "нет"
    if v < 0.25: return "<0.25"
    if v < 0.5: return "0.25-0.5"
    if v < 1.0: return "0.5-1"
    if v < 2.0: return "1-2"
    return ">=2"

df["room"] = df["nearest_opposing_R"].map(rb)
B = ["<0.25", "0.25-0.5", "0.5-1", "1-2", ">=2", "нет"]

def stats(g):
    n = len(g)
    if n == 0: return "—"
    rr = g["q"].astype(float)
    sd = rr.std(ddof=1) if n > 1 else 0.0
    ci = 1.96 * sd / np.sqrt(n) if n > 1 else 0.0
    return f"{n} / {rr.mean():+.3f} +-{ci:.3f}"

gp = df[(df["gate_rej"] == False) & df["q"].notna()]
print("gate-passed q:", len(gp))
for name, g in (("4-pass (все фильтры)", gp[gp["stage"] == "pass"]),
                ("отсеч. прочими (ms/dt/sweep)", gp[gp["stage"] != "pass"]),
                ("ИТОГО гейт-прошедшие", gp)):
    print(f"\n== {name} (n={len(g)}) ==")
    for b in B:
        print(f"   {b:9s} {stats(g[g['room'] == b])}")

print("\n== годы для ключевых корзин (гейт-прошедшие, объединённо) ==")
for b in ("<0.25", "0.25-0.5", "0.5-1", "нет"):
    row = []
    for y in ("2024", "2025", "2026"):
        g = gp[(gp["room"] == b) & (gp["year"] == y)]
        row.append(f"{y}: {stats(g)}")
    print(f"   {b:9s} | " + " | ".join(row))

print("\n== ноги (гейт-прошедшие) ==")
for lg in ("LONG", "SHORT"):
    g = gp[gp["direction"] == lg]
    cells = " | ".join(f"{b}: {stats(g[g['room'] == b])}" for b in ("<0.25", "0.25-1", ">=1", "нет"))
    print(f"   {lg}: {cells}")

# 4-pass отдельно по годам
print("\n== 4-pass по годам ==")
p4 = gp[gp["stage"] == "pass"]
for y in ("2024", "2025", "2026"):
    g = p4[p4["year"] == y]
    cells = " | ".join(f"{b}: {stats(g[g['room'] == b])}" for b in ("<0.25", "0.25-0.5", "0.5-1", "1-2", ">=2", "нет"))
    print(f"   {y}: {cells}")

# сколько базовых 998 в 4-pass, сверка
print("\n4-pass total:", len(p4), "(ожидание 1386)")
print("4-pass taken:", int(p4["taken"].sum()), "(ожидание 998)")
