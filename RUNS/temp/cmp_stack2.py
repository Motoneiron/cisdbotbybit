"""Доп.срез: ABL_FILT_OFF (канон без фильтров) vs live all (без A/V). Плюс посуточно-паровые пары для сверки."""
import os
import pickle

import numpy as np

CORE6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]


def stats(rows, key="r"):
    x = np.array([float(r[key]) for r in rows if r.get(key) is not None], float)
    n = len(x)
    tp = sum(1 for r in rows if str(r.get("outcome")) == "tp")
    sl = sum(1 for r in rows if str(r.get("outcome")) == "sl")
    if n == 0:
        return n, float("nan"), 0.0, tp, sl
    return n, float(x.mean()), float(x.sum()), tp, sl


def fmt(tag, s):
    n, m, sm, tp, sl = s
    print(f"{tag:30s} n={n:5d} avg={m:+.4f} sum={sm:+8.1f} tp={tp:4d} sl={sl:4d}")


print("=== ABL_FILT_OFF (канон-движок, детект без A+V+D) ===")
for year in (2023, 2024, 2025, 2026):
    rows = []
    for sym in CORE6:
        p = f"tf7_abl/ABL_FILT_OFF_{sym}_{year}.pkl"
        if os.path.exists(p):
            for r in pickle.load(open(p, "rb")):
                r = dict(r)
                r["r"] = r["r_net_mexc"]
                rows.append(r)
    fmt(f"FILT_OFF {year}", stats(rows))

print()
print("=== LIVE all (без A/V) — повтор для сверки ===")
for year in (2023, 2024, 2025, 2026):
    rows = []
    for sym in CORE6:
        p = f"live_filt/{sym}_{year}.pkl"
        if os.path.exists(p):
            rows.extend(pickle.load(open(p, "rb")))
    fmt(f"LIVE all {year}", stats(rows))

print()
print("=== По парам (2024), LIVE kept vs CANON ABL_MSS_MAIN ===")
for sym in CORE6:
    lv = []
    p = f"live_filt/{sym}_2024.pkl"
    if os.path.exists(p):
        for r in pickle.load(open(p, "rb")):
            sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
            if sw is None or not np.isfinite(sw) or sw < 0.40:
                continue
            if not soft and (vol is None or not np.isfinite(vol) or vol > 2.5):
                continue
            lv.append(r)
    cn = []
    p = f"tf7_abl/ABL_MSS_MAIN_{sym}_2024.pkl"
    if os.path.exists(p):
        for r in pickle.load(open(p, "rb")):
            r = dict(r)
            r["r"] = r["r_net_mexc"]
            cn.append(r)
    fmt(f"{sym} LIVE kept", stats(lv))
    fmt(f"{sym} CANON main", stats(cn))
