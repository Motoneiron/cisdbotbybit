# -*- coding: utf-8 -*-
"""Smoke check для nofilter-дампа: теги, категории, сверка с базой."""
import pickle, os

NF = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\smoke_rows_tf1v2_nofilter\ADA_2024.pkl"
BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx\smoke_rows_tf1v2\ADA_2024.pkl"

nf = pickle.load(open(NF, "rb"))
base = pickle.load(open(BASE, "rb"))
print("nofilter rows:", len(nf), "| base rows:", len(base))

cats = {}
for r in nf:
    k = "taken" if r.get("taken") else (r.get("skip_reason") or "?")
    cats[k] = cats.get(k, 0) + 1
print("nofilter categories:", cats)

tags = {}
for r in nf:
    combo = (bool(r.get("gate_rej")), bool(r.get("ms_rej")), bool(r.get("dt_rej")), bool(r.get("sweep_rej")))
    tags[combo] = tags.get(combo, 0) + 1
print("tag combos (gate,ms,dt,sweep):")
for k in sorted(tags, key=lambda x: (-sum(x), x)):
    print("   ", k, "->", tags[k])

allfalse = [r for r in nf if not (r.get("gate_rej") or r.get("ms_rej") or r.get("dt_rej") or r.get("sweep_rej"))]
print("all-tags-false:", len(allfalse), "(ожидание: база 6)")
if base:
    bk = {(r["sym"], r["direction"], r["scan"], r["cbt"]) for r in base}
    ak = {(r["sym"], r["direction"], r["scan"], r["cbt"]) for r in allfalse}
    print("all-false == base keys:", bk == ak, "| only in base:", len(bk - ak), "| only in all-false:", len(ak - bk))

print("\nSAMPLE taken row (nofilter):")
taken = [r for r in nf if r.get("taken")]
for r in taken[:2]:
    print({k: r[k] for k in ("scan", "direction", "outcome", "r", "sp", "gate_rej", "ms_rej", "dt_rej", "sweep_rej", "sv", "c2c_min", "sp_pct", "htf_sweep_level") if k in r})

print("\nSAMPLE gate-rejected signal:")
g = next((r for r in nf if r.get("gate_rej")), None)
if g:
    print({k: g.get(k) for k in ("scan", "direction", "taken", "skip_reason", "outcome_cf", "r_cf", "gate_rej", "sv", "sp_pct")})
print("\nSAMPLE min_stop-rejected:")
m = next((r for r in nf if r.get("ms_rej") and not r.get("gate_rej")), None)
if m:
    print({k: m.get(k) for k in ("scan", "direction", "taken", "skip_reason", "outcome_cf", "r_cf", "sp_pct")})
print("\nSAMPLE dt-rejected:")
d = next((r for r in nf if r.get("dt_rej") and not r.get("gate_rej") and not r.get("ms_rej")), None)
if d:
    print({k: d.get(k) for k in ("scan", "direction", "taken", "skip_reason", "outcome_cf", "r_cf", "c2c_min")})
print("\nSAMPLE sweep-rejected:")
s = next((r for r in nf if r.get("sweep_rej") and not r.get("gate_rej") and not r.get("ms_rej") and not r.get("dt_rej")), None)
if s:
    print({k: s.get(k) for k in ("scan", "direction", "taken", "skip_reason", "outcome_cf", "r_cf", "why_sw")})
