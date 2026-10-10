"""classify6.py — классы live-only по 6 парам 2024 (на данных canon_events + live_filt).

Мэтч (как в classify_liveonly): paired = канонный трейд с entry_ts ±6 мин от scan;
иначе ближайший канонный сигнал (cbt в [scan-4h, scan+5m]) → его судьба.
"""
import os
import pickle

import numpy as np
import pandas as pd

PAIRS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]
YEAR = 2024


def keep(r):
    sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
    if sw is None or not np.isfinite(sw) or sw < 0.40:
        return False
    if soft:
        return True
    return vol is not None and np.isfinite(vol) and vol <= 2.5


all_out = []
for sym in PAIRS:
    lp = f"live_filt/{sym}_{YEAR}.pkl"
    cp = f"canon_events/{sym}_{YEAR}.pkl"
    if not (os.path.exists(lp) and os.path.exists(cp)):
        print(f"{sym}: пропуск (feats={os.path.exists(lp)}, canon={os.path.exists(cp)})")
        continue
    lrows = [r for r in pickle.load(open(lp, "rb")) if keep(r)]
    cev = pickle.load(open(cp, "rb"))
    sigs = cev["signals"]
    dec = {d["hash"]: d for d in cev["decisions"]}
    trades = cev["trades"]
    tr_fill = {t["hash"] for t in trades}
    # индекс сигналов по времени cbt
    sig_ts = []
    for s in sigs:
        try:
            t = pd.Timestamp(s["cbt"])
        except Exception:
            continue
        sig_ts.append((t, s))
    tr_by_dir = {}
    for t in trades:
        tr_by_dir.setdefault(t["direction"], []).append(t)

    out = []
    for r in lrows:
        ts = pd.Timestamp(r["scan"])
        d = r["direction"]
        paired = False
        for t in tr_by_dir.get(d, []):
            try:
                dt = abs((pd.Timestamp(t["entry_ts"]) - ts).total_seconds())
            except Exception:
                continue
            if dt <= 360:
                paired = True
                break
        if paired:
            cls = "paired"
        else:
            cands = [(abs((st - ts).total_seconds()), s) for st, s in sig_ts
                     if s["direction"] == d and (ts - pd.Timedelta(hours=4)) <= st <= (ts + pd.Timedelta(minutes=5))]
            if not cands:
                cls = "notseen"
            else:
                cands.sort(key=lambda x: x[0])
                s = cands[0][1]
                h = s["hash"]
                if h in tr_fill:
                    cls = "fill"          # странность
                elif h in dec and dec[h]["accepted"]:
                    cls = "accept_nofill"
                elif s["fib"]:
                    cls = "reject_market"
                else:
                    cls = "reject_other"
        out.append({"sym": sym, "scan": r["scan"], "dir": d, "r": float(r["r"]),
                    "out": r["outcome"], "cls": cls})
    O = pd.DataFrame(out)
    all_out.append(O)
    g = O.groupby("cls")["r"].agg(["count", "sum", "mean"])
    print(f"\n== {sym} {YEAR} ==")
    print(g.round(3).to_string())
    print("  live-only:", round(O[O.cls != 'paired']['r'].sum(), 1), "n=", (O.cls != 'paired').sum())

A = pd.concat(all_out)
print("\n\n===== ВСЕ 6 ПАР 2024 =====")
g = A.groupby("cls")["r"].agg(["count", "sum", "mean"])
g["tp"] = A[A.out == "tp"].groupby("cls")["r"].count()
g["sl"] = A[A.out == "sl"].groupby("cls")["r"].count()
print(g.round(3).to_string())

print("\n--- по парам: notseen ---")
for sym in PAIRS:
    o = A[(A.sym == sym) & (A.cls == "notseen")]
    if len(o):
        print(f"  {sym:5} n={len(o):4} sum={o['r'].sum():+7.1f} avg={o['r'].mean():+.3f}  tp={int((o.out=='tp').sum())} sl={int((o.out=='sl').sum())}")
print("\n--- по парам: reject_market ---")
for sym in PAIRS:
    o = A[(A.sym == sym) & (A.cls == "reject_market")]
    if len(o):
        print(f"  {sym:5} n={len(o):4} sum={o['r'].sum():+7.1f} avg={o['r'].mean():+.3f}  tp={int((o.out=='tp').sum())} sl={int((o.out=='sl').sum())}")
A.to_csv("classify6_out.csv", index=False)
print("\nsaved classify6_out.csv")
