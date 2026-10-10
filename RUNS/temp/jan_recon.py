"""jan_recon.py — месячная сверка live vs canon (SOL 2024) + живой итог по всем парам."""
import pickle

import numpy as np
import pandas as pd

CORE6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]


def filt(rows):
    out = []
    for r in rows:
        sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
        if sw is None or not np.isfinite(sw) or sw < 0.40:
            continue
        if not soft and (vol is None or not np.isfinite(vol) or vol > 2.5):
            continue
        out.append(r)
    return out


print("==== SOL 2024: LIVE (фильтр) по месяцам ====")
L = pd.DataFrame(filt(pickle.load(open("live_filt/SOL_2024.pkl", "rb"))))
L["ts"] = pd.to_datetime(L["scan"])
L["m"] = L["ts"].dt.to_period("M")
g = L.groupby("m")["r"].agg(["count", "sum", "mean"])
print(g.round(3).to_string())
print(f"LIVE SOL 2024 TOTAL: n={len(L)} sum={L['r'].sum():+.1f} avg={L['r'].mean():+.3f}")

print("\n==== SOL 2024: CANON (ABL_MSS_MAIN) по месяцам ====")
C = pd.DataFrame(pickle.load(open("tf7_abl/ABL_MSS_MAIN_SOL_2024.pkl", "rb")))
C["rr"] = C["r_net_mexc"].astype(float)
ccol = "entry_ts" if "entry_ts" in C.columns else ("created_ts" if "created_ts" in C.columns else None)
print("canon cols:", list(C.columns)[:20])
if ccol:
    C["ts"] = pd.to_datetime(C[ccol])
    C["m"] = C["ts"].dt.to_period("M")
    g2 = C.groupby("m")["rr"].agg(["count", "sum", "mean"])
    print(g2.round(3).to_string())
print(f"CANON SOL 2024 TOTAL: n={len(C)} sum={C['rr'].sum():+.1f} avg={C['rr'].mean():+.3f}")

print("\n==== ВСЕ ПАРЫ: live(фильтр) vs canon по годам ====")
print(f"{'pair':6} {'year':5} | {'live_n':>7} {'live_sum':>9} {'live_avg':>9} | {'can_n':>6} {'can_sum':>8} {'can_avg':>8}")
tl = tc = 0.0
nl = nc = 0
for sym in CORE6:
    for year in (2023, 2024, 2025, 2026):
        try:
            lr = filt(pickle.load(open(f"live_filt/{sym}_{year}.pkl", "rb")))
            cr = pickle.load(open(f"tf7_abl/ABL_MSS_MAIN_{sym}_{year}.pkl", "rb"))
        except FileNotFoundError:
            continue
        ls = sum(float(x["r"]) for x in lr)
        cs = sum(float(x["r_net_mexc"]) for x in cr)
        la = ls / len(lr) if lr else 0
        ca = cs / len(cr) if cr else 0
        print(f"{sym:6} {year} | {len(lr):7} {ls:+9.1f} {la:+9.3f} | {len(cr):6} {cs:+8.1f} {ca:+8.3f}")
        tl += ls
        tc += cs
        nl += len(lr)
        nc += len(cr)
print(f"\nTOTAL live: n={nl} sum={tl:+.1f} avg={tl/nl:+.4f}")
print(f"TOTAL canon: n={nc} sum={tc:+.1f} avg={tc/nc:+.4f}")
