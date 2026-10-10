"""Матч v2: live.scan <-> canon.entry_ts (+-6 мин). Кто кому пара, у кого какой r."""
import pickle
import sys

import numpy as np
import pandas as pd

CORE6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]


def live_rows(sym, year):
    rows = pickle.load(open(f"live_filt/{sym}_{year}.pkl", "rb"))
    out = []
    for r in rows:
        sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
        if sw is None or not np.isfinite(sw) or sw < 0.40:
            continue
        if not soft and (vol is None or not np.isfinite(vol) or vol > 2.5):
            continue
        out.append(r)
    return out


def canon_rows(sym, year):
    rows = pickle.load(open(f"tf7_abl/ABL_MSS_MAIN_{sym}_{year}.pkl", "rb"))
    out = []
    for r in rows:
        r = dict(r)
        r["rr"] = float(r["r_net_mexc"])
        out.append(r)
    return out


def study(sym, year, tol=6):
    L = pd.DataFrame(live_rows(sym, year))
    C = pd.DataFrame(canon_rows(sym, year))
    if L.empty or C.empty:
        print(f"== {sym} {year}: пусто")
        return
    L["ts"] = pd.to_datetime(L["scan"])
    C["ts"] = pd.to_datetime(C["entry_ts"])
    L["r"] = L["r"].astype(float)
    cands = []
    for ci, c in C.iterrows():
        for li, l in L.iterrows():
            if l["direction"] != c["direction"]:
                continue
            dt = (l["ts"] - c["ts"]).total_seconds() / 60.0
            if abs(dt) <= tol:
                cands.append((abs(dt), ci, li, dt))
    cands.sort(key=lambda x: x[0])
    usedC, usedL = set(), set()
    pairs = []
    for adt, ci, li, dt in cands:
        if ci in usedC or li in usedL:
            continue
        usedC.add(ci)
        usedL.add(li)
        pairs.append((ci, li, dt))
    both = [(C.loc[ci], L.loc[li], dt) for ci, li, dt in pairs]
    noL = C.loc[[ci for ci in C.index if ci not in usedC]]
    noC = L.loc[[li for li in L.index if li not in usedL]]
    same = sum(1 for c, l, dt in both if c["outcome"] == l["outcome"])
    print(f"== {sym} {year}: canon={len(C)} live={len(L)}")
    print(f"   paired={len(both)} [исход совпал {same}] | canon-only={len(noL)} | live-only={len(noC)}")
    if both:
        rc = np.array([float(c["rr"]) for c, l, dt in both])
        rl = np.array([float(l["r"]) for c, l, dt in both])
        dts = np.array([dt for c, l, dt in both])
        print(f"   paired avg r: canon={rc.mean():+.4f} live={rl.mean():+.4f}  (dt мин: med={np.median(dts):+.1f} p10={np.percentile(dts,10):+.1f} p90={np.percentile(dts,90):+.1f})")
    if len(noL):
        rr = noL["rr"].astype(float).values
        print(f"   canon-only: n={len(rr)} avg={rr.mean():+.4f} sum={rr.sum():+.0f} tp={int((noL.outcome=='tp').sum())} sl={int((noL.outcome=='sl').sum())}")
    if len(noC):
        rr = noC["r"].astype(float).values
        print(f"   live-only:  n={len(rr)} avg={rr.mean():+.4f} sum={rr.sum():+.0f} tp={int((noC.outcome=='tp').sum())} sl={int((noC.outcome=='sl').sum())}")
    # примеры расхождений исходов среди пар
    shown = 0
    for c, l, dt in both:
        if c["outcome"] != l["outcome"] and shown < 8:
            print(f"     mismatch: {c['direction']:5s} canon {c['ts']} {c['outcome']:4s}(r={c['rr']:+.2f}) live {l['ts']} {l['outcome']:4s}(r={l['r']:+.2f})")
            shown += 1
    # примеры canon-only
    shown = 0
    for _, c in noL.head(8).iterrows():
        print(f"     canon-only ex: {c['direction']:5s} entry={c['ts']} created={c['created_ts']} {c['outcome']:4s} r={c['rr']:+.2f}")
        shown += 1
    shown = 0
    for _, l in noC.head(8).iterrows():
        print(f"     live-only  ex: {l['direction']:5s} scan={l['ts']} {l['outcome']:4s} r={l['r']:+.2f}")
        shown += 1


if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or [2024]
    for y in years:
        for s in CORE6:
            study(s, y)
        print()
