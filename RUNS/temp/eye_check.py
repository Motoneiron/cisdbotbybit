"""Глазами: времена сделок live vs canon (SOL 2024)."""
import pickle

import numpy as np
import pandas as pd

L = pickle.load(open("live_filt/SOL_2024.pkl", "rb"))
L = [
    r
    for r in L
    if (r.get("sw") is not None and np.isfinite(r["sw"]) and r["sw"] >= 0.40)
    and (r.get("soft") or (r.get("vol") is not None and np.isfinite(r["vol"]) and r["vol"] <= 2.5))
]
L = sorted(L, key=lambda r: r["scan"])
C = pickle.load(open("tf7_abl/ABL_MSS_MAIN_SOL_2024.pkl", "rb"))
C = sorted(C, key=lambda r: r["created_ts"])

print(f"live kept n={len(L)} | canon n={len(C)}")
print()
print(f"{'LIVE (scan, dir, outcome)':<42}{'| CANON (created_ts, entry_ts, dir, outcome)'}")
for i in range(min(40, max(len(L), len(C)))):
    ls = ""
    cs = ""
    if i < len(L):
        r = L[i]
        ls = f"{r['scan']} {r['direction']:5s} {r['outcome']:4s} r={r['r']:+.2f}"
    if i < len(C):
        r = C[i]
        cs = f"{r['created_ts']} -> {r['entry_ts']} {r['direction']:5s} {r['outcome']:4s}"
    print(f"{ls:<42}| {cs}")

print()
print("=== канонные: распределение created_ts минута-в-часе ===")
ct = pd.to_datetime([r["created_ts"] for r in C])
print(ct.minute.value_counts().sort_index().to_dict())
et = pd.to_datetime([r["entry_ts"] for r in C])
print("entry минута-в-часе:", et.minute.value_counts().sort_index().to_dict())

print()
print("=== live: распределение scan минута-в-часе ===")
st = pd.to_datetime([r["scan"] for r in L])
print(st.minute.value_counts().sort_index().to_dict())
