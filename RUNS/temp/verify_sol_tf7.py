"""Независимая проверка отчёта SOL_TF7_RESURRECT: пересчёт из sol_tf7/*.pkl.

Считается мой собственный пересчёт: n, WR, avg, t, Σ (MEXC), Bybit-пересчёт.
Плюс сверки идентичности: C1 vs C2 (якорь), C2 vs C3 (MARKET).
"""
import glob
import pickle

import numpy as np
import pandas as pd

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/sol_tf7"
MEXC_M, MEXC_T = 0.0006, 0.0008
BYBIT_M, BYBIT_T = 0.00036, 0.0010

rows = []
for f in sorted(glob.glob(OUT + "/*.pkl")):
    rows.extend(pickle.load(open(f, "rb")))
d = pd.DataFrame(rows)
print("файлов:", len(glob.glob(OUT + "/*.pkl")), "| строк:", len(d))


def fee_r(kind, outcome, sp, maker, taker):
    if sp <= 0:
        return 0.0
    entry = maker if str(kind).upper() == "LIMIT" else taker
    exit_ = maker if outcome == "tp" else taker
    return (entry + exit_) / sp


d["fee_mexc"] = [fee_r(k, o, s, MEXC_M, MEXC_T) for k, o, s in zip(d.entry_kind, d.outcome, d.sp)]
d["fee_bybit"] = [fee_r(k, o, s, BYBIT_M, BYBIT_T) for k, o, s in zip(d.entry_kind, d.outcome, d.sp)]
d["gross"] = d.r_net_mexc + d.fee_mexc
d["net_bybit"] = d.gross - d.fee_bybit


def stat(q, col="r_net_mexc"):
    n = len(q)
    if n == 0:
        return "n=0"
    tp = int((q.outcome == "tp").sum())
    sl = int((q.outcome == "sl").sum())
    wr = 100 * tp / max(1, tp + sl)
    sd = q[col].std(ddof=1)
    t = q[col].mean() / (sd / np.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    return f"n={n:5d} WR={wr:5.1f}% avg={q[col].mean():+.4f} t={t:+6.2f} Σ={q[col].sum():+8.1f}"


for cfg in sorted(d.config.unique()):
    q = d[d.config == cfg]
    print(f"\n=== {cfg}")
    print("  все        ", stat(q))
    print("  LIMIT      ", stat(q[q.entry_kind == "LIMIT"]))
    print("  MARKET     ", stat(q[q.entry_kind == "MARKET"]))
    print("  2020-23    ", stat(q[q.year <= 2023]))
    print("  2024-26    ", stat(q[q.year >= 2024]))
    ql = q[(q.year >= 2024) & (q.entry_kind == "LIMIT")]
    print("  24-26 LIMIT", stat(ql), "| Bybit:", stat(ql, "net_bybit"))
    print("  по годам:")
    for y, yq in q.groupby("year"):
        print(f"    {y}", stat(yq), "| bybit:", stat(yq, "net_bybit"))

c1 = d[d.config == "C1_oldfill_all_fib"]
c2 = d[d.config == "C2_causal_all_fib"]
c3 = d[d.config == "C3_causal_all_scanclose"]
h1 = set(map(str, c1.hash))
h2 = set(map(str, c2.hash))
print(f"\nC1 n={len(c1)} vs C2 n={len(c2)}: общих хешей={len(h1 & h2)}; C1-only={len(h1 - h2)}; C2-only={len(h2 - h1)}")
print(f"C1 Σ={c1.r_net_mexc.sum():+.1f} | C2 Σ={c2.r_net_mexc.sum():+.1f}")
m2 = set(map(str, c2[c2.entry_kind == "MARKET"].hash))
m3 = set(map(str, c3[c3.entry_kind == "MARKET"].hash))
print(f"C2 MARKET n={len(m2)} vs C3 MARKET n={len(m3)}: общих={len(m2 & m3)}; C2-only={len(m2 - m3)}; C3-only={len(m3 - m2)}")
l2 = set(map(str, c2[c2.entry_kind == "LIMIT"].hash))
l3 = set(map(str, c3[c3.entry_kind == "LIMIT"].hash))
print(f"C2 LIMIT n={len(l2)} vs C3 LIMIT n={len(l3)}: общих={len(l2 & l3)}")
