# -*- coding: utf-8 -*-
"""Smoke check: new htfctx dump vs original smoke_stopt_tf1v2."""
import pickle, os
import pandas as pd

NEW = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx\smoke_rows_tf1v2\ADA_2024.pkl"
OLD = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\smoke_stopt_tf1v2\ADA_2024.pkl"

new = pickle.load(open(NEW, "rb"))
old = pickle.load(open(OLD, "rb")) if os.path.exists(OLD) else []
print("NEW rows:", len(new), " OLD rows:", len(old))

cats = {}
for r in new:
    k = "taken" if r.get("taken") else (r.get("skip_reason") or "?")
    cats[k] = cats.get(k, 0) + 1
print("categories:", cats)

taken_new = [r for r in new if r.get("taken")]
for r in taken_new[:2]:
    print("\nTAKEN sample:")
    for k in sorted(r):
        print(f"   {k} = {r[k]}")

for reason in ("busy", "htf_taken", "tp_touched", "no_fill"):
    row = next((r for r in new if r.get("skip_reason") == reason), None)
    if row:
        print(f"\nSKIP[{reason}]: dir={row['direction']} scan={row['scan']} entry={row['entry']} "
              f"outcome_cf={row['outcome_cf']} r_cf={row['r_cf']} sweep_lvl={row['htf_sweep_level']} "
              f"cisd={row['cisd_level']}")

# parity on taken keys vs old
ok = None
if old:
    kn = {(r["sym"], r["direction"], r["scan"], r["cbt"], r["outcome"], round(r["r"], 10)) for r in new if r.get("taken")}
    ko = {(r["sym"], r["direction"], r["scan"], r["cbt"], r["outcome"], round(r["r"], 10)) for r in old}
    print("\nparity: new_taken", len(kn), "old", len(ko), "equal:", kn == ko)
    print("only_new:", len(kn - ko), "only_old:", len(ko - kn))
    ok = kn == ko
print("RESULT:", "PASS" if ok in (True, None) else "FAIL")
