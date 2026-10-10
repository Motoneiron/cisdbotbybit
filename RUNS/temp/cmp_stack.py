"""Свод: live_filt (живой код) vs канон tf7_abl (BASE 1m-MSS, ABL_MSS_MAIN 5m-MSS), core-6."""
import glob
import os
import pickle

import numpy as np

CORE6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]


def stats(rows):
    x = np.array([float(r["r"]) for r in rows if r.get("r") is not None], float)
    n = len(x)
    tp = sum(1 for r in rows if str(r.get("outcome")) == "tp")
    sl = sum(1 for r in rows if str(r.get("outcome")) == "sl")
    tm = sum(1 for r in rows if str(r.get("outcome")) == "time")
    if n == 0:
        return n, float("nan"), 0.0, tp, sl, tm
    return n, float(x.mean()), float(x.sum()), tp, sl, tm


def fmt(tag, s):
    n, m, sm, tp, sl, tm = s
    print(f"{tag:28s} n={n:5d} avg={m:+.4f} sum={sm:+8.1f} tp={tp:4d} sl={sl:4d} time={tm:3d}")


print("=== LIVE_FILT (живой код, bybit fees): kept by both (sw>=.40 & (soft | vol<=2.5)) ===")
for year in (2023, 2024, 2025, 2026):
    rows = []
    for sym in CORE6:
        p = f"live_filt/{sym}_{year}.pkl"
        if not os.path.exists(p):
            continue
        for r in pickle.load(open(p, "rb")):
            sw = r.get("sw")
            vol = r.get("vol")
            soft = r.get("soft")
            if sw is None or not np.isfinite(sw) or sw < 0.40:
                continue
            if not soft and (vol is None or not np.isfinite(vol) or vol > 2.5):
                continue
            rows.append(r)
    fmt(f"LIVE kept {year}", stats(rows))

print()
print("=== LIVE_FILT: all (A+V off, как есть) — для справки ===")
for year in (2023, 2024, 2025, 2026):
    rows = []
    for sym in CORE6:
        p = f"live_filt/{sym}_{year}.pkl"
        if os.path.exists(p):
            rows.extend(pickle.load(open(p, "rb")))
    fmt(f"LIVE all {year}", stats(rows))

print()
for cfg in ("ABL_MSS_MAIN", "BASE_rerun"):
    print(f"=== CANON {cfg} (r_net_mexc) ===")
    for year in (2023, 2024, 2025, 2026):
        rows = []
        for sym in CORE6:
            p = f"tf7_abl/{cfg}_{sym}_{year}.pkl"
            if os.path.exists(p):
                for r in pickle.load(open(p, "rb")):
                    r = dict(r)
                    r["r"] = r["r_net_mexc"]
                    rows.append(r)
        fmt(f"{cfg} {year}", stats(rows))

print()
print("=== CANON totals 2024-26 ===")
for cfg in ("ABL_MSS_MAIN", "BASE_rerun"):
    rows = []
    for year in (2024, 2025, 2026):
        for sym in CORE6:
            p = f"tf7_abl/{cfg}_{sym}_{year}.pkl"
            if os.path.exists(p):
                for r in pickle.load(open(p, "rb")):
                    r = dict(r)
                    r["r"] = r["r_net_mexc"]
                    rows.append(r)
    fmt(cfg, stats(rows))
