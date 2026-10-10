# -*- coding: utf-8 -*-
"""Probe 1: inventory of stopt_tf1v2 results + field check. (HTF Context task)"""
import pickle, glob, os, json
import pandas as pd

ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2"
PAIRS10 = ["SOL","DOGE","KAS","ADA","LINK","LTC","XRP","BTC","AVAX","TON"]

files = sorted(glob.glob(os.path.join(ROOT, "*.pkl")))
allpairs = sorted({os.path.basename(f).rsplit("_",1)[0] for f in files})
print("files:", len(files))
print("pairs:", allpairs)

tot_n = 0; tot_r = 0.0; tot_tp=0; tot_sl=0; tot_time=0
per_pair = {}
rows_sample = []
for sym in PAIRS10:
    n=r=0; oc={}
    for y in (2024,2025,2026):
        p = os.path.join(ROOT, f"{sym}_{y}.pkl")
        if not os.path.exists(p):
            print("MISSING", p); continue
        rows = pickle.load(open(p,"rb"))
        for row in rows:
            if len(rows_sample) < 3 and y==2024 and len(rows)>0 and row is rows[0]:
                rows_sample.append(dict(row))
        n += len(rows); r += sum(x["r"] for x in rows)
        for x in rows: oc[x["outcome"]] = oc.get(x["outcome"],0)+1
    per_pair[sym] = (n, round(r,1), oc)
    tot_n += n; tot_r += r
    tot_tp += oc.get("tp",0); tot_sl += oc.get("sl",0); tot_time += oc.get("time",0)

for s,(n,r,oc) in per_pair.items():
    print(f"{s:5s} n={n:4d}  sumR={r:+7.1f}  {oc}")
print(f"TOTAL n={tot_n} sumR={tot_r:+.1f} tp/sl/time={tot_tp}/{tot_sl}/{tot_time}")

print("\nSAMPLE ROWS:")
for row in rows_sample[:3]:
    print({k: row[k] for k in row})

# check scan vs cbt relation
cnt=0
for sym in ["SOL","DOGE"]:
    rows = pickle.load(open(os.path.join(ROOT, f"{sym}_2024.pkl"),"rb"))
    for row in rows[:5]:
        d = (pd.Timestamp(row["scan"]) - pd.Timestamp(row["cbt"])).total_seconds()/60.0
        d2 = (pd.Timestamp(row["cbt"]) - pd.Timestamp(row["tbt"])).total_seconds()/60.0
        print(f"{sym} scan-cbt={d} min, cbt-tbt={d2} min, outcome={row['outcome']}, sp={row['sp']:.4f}")
