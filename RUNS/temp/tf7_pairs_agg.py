"""Агрегатор tf7_pairs: C5/C4 по парам (MEXC + пересчёт Bybit)."""
import glob
import pickle

import numpy as np
import pandas as pd

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_pairs"
MEXC_M, MEXC_T = 0.0006, 0.0008
BYBIT_M, BYBIT_T = 0.00036, 0.0010

rows = []
for f in sorted(glob.glob(OUT + "/*.pkl")):
    rows.extend(pickle.load(open(f, "rb")))
d = pd.DataFrame(rows)
print("файлов:", len(glob.glob(OUT + "/*.pkl")), "| строк:", len(d))
print("годы:", sorted(d.year.unique().tolist()), "| пары:", sorted(d.sym.unique().tolist()))


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
    return f"n={n:5d} WR={wr:5.1f}% avg={q[col].mean():+.4f} t={t:+5.2f} Σ={q[col].sum():+8.1f}"


for cfg in sorted(d.config.unique()):
    qc = d[d.config == cfg]
    print(f"\n======== {cfg}")
    for sym in sorted(qc.sym.unique()):
        q = qc[qc.sym == sym]
        e = q[q.year <= 2023]
        l = q[q.year >= 2024]
        print(f"  {sym:5s} всё : {stat(q)}")
        print(f"        20-23: {stat(e)}")
        print(f"        24-26: {stat(l)} | Bybit: {stat(l, 'net_bybit')}")
    lt = qc[qc.year >= 2024]
    print(f"  ИТОГО: {stat(qc)}")
    print(f"  ИТОГО 24-26: {stat(lt)} | Bybit 24-26: {stat(lt, 'net_bybit')}")

print("\n==== ПО ГОДАМ (все пары) ====")
for cfg in sorted(d.config.unique()):
    qc = d[d.config == cfg]
    print(f"\n{cfg}")
    for y in sorted(qc.year.unique()):
        q = qc[qc.year == y]
        print(f"  {y}: {stat(q)} | bybit: {stat(q, 'net_bybit')}")

print("\n==== LONG/SHORT (пул 10 пар) ====")
for cfg in sorted(d.config.unique()):
    qc = d[d.config == cfg]
    lt = qc[qc.year >= 2024]
    for lbl, q in (("все", qc), ("24-26", lt)):
        for dd in ("LONG", "SHORT"):
            qq = q[q["direction"] == dd]
            print(f"{cfg} {lbl:6s} {dd:5s}: {stat(qq)} | bybit: {stat(qq, 'net_bybit')}")

print("\n==== ИТОГИ Bybit (все годы / 24-26) ====")
for cfg in sorted(d.config.unique()):
    qc = d[d.config == cfg]
    print(f"{cfg} все  : {stat(qc, 'net_bybit')}")
    print(f"{cfg} 24-26: {stat(qc[qc.year >= 2024], 'net_bybit')}")
