"""classify_liveonly.py — раскладываем live-only записи SOL 2024 по судьбе у канона.

Классы (по канонному логу года): canon не видел (notseen) / видел-но-не-принял (det_only) /
отклонил (reject_market=fib-класс, reject_other) / принял-но-не-филл (accept_nofill) /
фактически филл (загадка: должен был быть paired).
"""
import pickle
import re

import numpy as np
import pandas as pd

CORE6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]

det_re = re.compile(
    r"\[DET \] scan=(\S+ \S+) (\w+) (LONG|SHORT) cbt=(\S+ \S+) swc=(\S+ \S+) e=([\d.\-]+) fib=(\d) kind=(\w+)"
)
try_re = re.compile(
    r"\[TRY \] scan=(\S+ \S+) (\w+) (LONG|SHORT) cbt=(\S+ \S+) swc=(\S+ \S+) e=([\d.\-]+) -> (REJECT|ACCEPT)"
)
fill_re = re.compile(r"\[FILL\] (\w+)")

ev = {}
try_of_hash = {}
fills = set()
for line in open("trace_canon_year_out.txt", encoding="utf-8"):
    m = det_re.search(line)
    if m:
        cbt, d = m.group(4), m.group(3)
        e = ev.setdefault((cbt, d), dict(det=False, try_=False, fates=set()))
        e["det"] = True
        continue
    m = try_re.search(line)
    if m:
        scan, h, d, cbt, e_ = m.group(1), m.group(2), m.group(3), m.group(4), m.group(6)
        e = ev.setdefault((cbt, d), dict(det=False, try_=False, fates=set()))
        e["try_"] = True
        try_of_hash[h] = (cbt, d)
        if m.group(7) == "ACCEPT":
            e["fates"].add("accept")
        else:
            if "kind=MARKET" in line:
                e["fates"].add("reject_market")
            else:
                e["fates"].add("reject_other")
        continue
    m = fill_re.search(line)
    if m:
        fills.add(m.group(1))

for h in fills:
    if h in try_of_hash:
        ev[try_of_hash[h]]["fates"].add("fill")

PRIO = ["fill", "accept", "reject_market", "reject_other"]
ev_list = []
for (cbt, d), e in ev.items():
    fate = None
    for f in PRIO:
        if f in e["fates"]:
            fate = f
            break
    if fate is None:
        fate = "det_only" if e["det"] else "unknown"
    ev_list.append((pd.Timestamp(cbt), d, fate, cbt))
ev_df = pd.DataFrame(ev_list, columns=["ts", "dir", "fate", "cbt"]).sort_values("ts")
print("канонных сигнальных событий:", len(ev_df))
print(ev_df["fate"].value_counts().to_string())

# --- live
rows = pickle.load(open("live_filt/SOL_2024.pkl", "rb"))
L = []
for r in rows:
    sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
    if sw is None or not np.isfinite(sw) or sw < 0.40:
        continue
    if not soft and (vol is None or not np.isfinite(vol) or vol > 2.5):
        continue
    L.append(r)
L = pd.DataFrame(L)
L["ts"] = pd.to_datetime(L["scan"])

# --- canon trades (paired check)
C = pd.DataFrame(pickle.load(open("tf7_abl/ABL_MSS_MAIN_SOL_2024.pkl", "rb")))
C["ts"] = pd.to_datetime(C["entry_ts"])
C["dir"] = C["direction"]

out = []
for _, r in L.iterrows():
    ts, d = r["ts"], r["direction"]
    paired = ((C["dir"] == d) & (abs((C["ts"] - ts).dt.total_seconds()) <= 360)).any()
    if paired:
        out.append(dict(scan=r["scan"], dir=d, r=r["r"], out=r["outcome"], cls="paired"))
        continue
    cand = ev_df[(ev_df["dir"] == d) & (ev_df["ts"] >= ts - pd.Timedelta(hours=4)) & (ev_df["ts"] <= ts + pd.Timedelta(minutes=5))]
    if cand.empty:
        cls = "notseen"
    else:
        cand = cand.assign(dt=(cand["ts"] - ts).abs())
        cls = cand.sort_values("dt").iloc[0]["fate"]
    out.append(dict(scan=r["scan"], dir=d, r=r["r"], out=r["outcome"], cls=cls))

O = pd.DataFrame(out)
O["r"] = O["r"].astype(float)
print("\n==== live SOL 2024 по классам ====")
g = O.groupby("cls")["r"].agg(["count", "sum", "mean"])
g["tp"] = O[O["out"] == "tp"].groupby("cls")["r"].count()
g["sl"] = O[O["out"] == "sl"].groupby("cls")["r"].count()
print(g.round(3).to_string())
print("\n paired total:", O[O["cls"] == "paired"]["r"].sum().round(1), " n=", (O["cls"] == "paired").sum())
lv = O[O["cls"] != "paired"]
print(" live-only total:", lv["r"].sum().round(1), " n=", len(lv), " avg=", round(lv["r"].mean(), 3))
print("\nПримеры по классам:")
for cls in ["notseen", "det_only", "reject_market", "reject_other", "accept_nofill", "fill"]:
    sub = O[O["cls"] == cls].head(6)
    if len(sub):
        print(f"  {cls}:")
        for _, x in sub.iterrows():
            print(f"    {x['scan']} {x['dir']} {x['out']} r={x['r']:+.2f}")
O.to_csv("classify_liveonly_out.csv", index=False)
print("\nsaved classify_liveonly_out.csv")
