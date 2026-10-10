# -*- coding: utf-8 -*-
"""Паритет-сверка htfctx-дампа с эталоном stopt_tf1v2 (должно быть 1:1)."""
import glob
import os
import pickle

NEW = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx\rows_tf1v2"
OLD = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2"
PAIRS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC", "XRP", "BTC", "AVAX", "TON"]


def collect(d, only_taken=True):
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.pkl"))):
        sym = os.path.basename(f).rsplit("_", 1)[0]
        if sym not in PAIRS:
            continue
        for r in pickle.load(open(f, "rb")):
            if only_taken and not (r.get("taken", True) if "taken" in r else True):
                continue
            key = (r["sym"], r["direction"], r["scan"], r["cbt"])
            out[key] = r
    return out


n = collect(NEW)
o = collect(OLD)
print(f"new taken: {len(n)} | old taken: {len(o)}")

only_new = sorted(set(n) - set(o))
only_old = sorted(set(o) - set(n))
print(f"only_new: {len(only_new)} | only_old: {len(only_old)}")
for k in only_new[:5]:
    print("  NEW:", k)
for k in only_old[:5]:
    print("  OLD:", k)

common = set(n) & set(o)
bad_out = [(k, n[k]["outcome"], o[k]["outcome"]) for k in common if n[k]["outcome"] != o[k]["outcome"]]
bad_r = [(k, n[k]["r"], o[k]["r"]) for k in common if abs(float(n[k]["r"]) - float(o[k]["r"])) > 1e-12]
print(f"outcome mismatch: {len(bad_out)} | r mismatch: {len(bad_r)}")
for x in bad_out[:5]:
    print("  ", x)
for x in bad_r[:5]:
    print("  ", x)

sum_new = sum(float(v["r"]) for v in n.values())
sum_old = sum(float(v["r"]) for v in o.values())
tp = sum(1 for v in n.values() if v["outcome"] == "tp")
sl = sum(1 for v in n.values() if v["outcome"] == "sl")
tm = sum(1 for v in n.values() if v["outcome"] == "time")
print(f"new: n={len(n)} sumR={sum_new:+.1f} tp/sl/time={tp}/{sl}/{tm}")
print(f"old: n={len(o)} sumR={sum_old:+.1f}")
verdict = (len(only_new) == 0 and len(only_old) == 0 and not bad_out and not bad_r
           and abs(sum_new - sum_old) < 1e-6)
print("PARITY:", "PASS" if verdict else "FAIL")
