# -*- coding: utf-8 -*-
"""Sanity-доп: оставшиеся сверки ungated vs v2 (vd, liq_dist, ema_slope) + t_sw."""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/lr18_ungated_feats.pkl")
fe = pd.read_pickle(f"{BASE}/lr18_sol_feats.pkl")
v2 = pd.read_pickle(f"{BASE}/knn18_live_full.pkl")
k = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
v2i = v2.set_index(k(v2))
u = df.set_index(k(df))
common = u.index.intersection(v2i.index)
print(f"пересечение {len(common)}")

fei = fe.set_index(k(fe))
for col in ("liquidity_distance", "ema_slope_side"):
    common_f = u.index.intersection(fei.index)
    a = u.loc[common_f, col].astype(float)
    b = fei.loc[common_f, col].astype(float)
    ok = a.notna() & b.notna()
    m = (a[ok] - b[ok]).abs() <= 1e-5
    print(f"  {col:22} vs v2: match {int(m.sum())}/{int(ok.sum())} = {100*m.mean():.2f}%")

a = u.loc[common, "t_sw_min"].astype(float)
b = (pd.to_datetime(v2i.loc[common, "confirm_bar_time"]) - pd.to_datetime(v2i.loc[common, "trigger_bar_time"])).dt.total_seconds() / 60.0
ok = a.notna() & b.notna()
m = (a[ok] - b[ok]).abs() <= 1e-9
print(f"  {'t_sw_min':18} vs v2 cbt-tbt           : match {int(m.sum())}/{int(ok.sum())} = {100*m.mean():.2f}%")
print("DONE")
