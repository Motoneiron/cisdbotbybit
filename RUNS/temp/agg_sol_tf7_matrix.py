"""Сводка промежуточных pkl из sol_tf7_matrix.py."""
import glob
import pickle
from collections import defaultdict

import numpy as np
import pandas as pd

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/sol_tf7"
MEXC_M, MEXC_T = 0.0006, 0.0008
BYBIT_M, BYBIT_T = 0.00036, 0.0010


def fee_r(kind, outcome, sp, maker, taker):
    if sp <= 0:
        return 0.0
    entry = maker if str(kind).upper() == "LIMIT" else taker
    exit_ = maker if outcome == "tp" else taker
    return (entry + exit_) / sp


rows = []
for f in sorted(glob.glob(OUT + "/*.pkl")):
    recs = pickle.load(open(f, "rb"))
    rows.extend(recs)
d = pd.DataFrame(rows)
print("файлов", len(glob.glob(OUT + "/*.pkl")), "строк", len(d))
print("конфиги:", sorted(d.config.unique()) if len(d) else None)
print("годы по конфигу:")
if len(d):
    print(d.groupby("config")["year"].agg(["min", "max", "nunique", "count"]))

    d["fee_mexc"] = [fee_r(k, o, s, MEXC_M, MEXC_T) for k, o, s in zip(d.entry_kind, d.outcome, d.sp)]
    d["fee_bybit"] = [fee_r(k, o, s, BYBIT_M, BYBIT_T) for k, o, s in zip(d.entry_kind, d.outcome, d.sp)]
    d["gross"] = d["r_net_mexc"] + d["fee_mexc"]
    d["net_bybit"] = d["gross"] - d["fee_bybit"]

    def blk(title, q):
        n = len(q)
        if n == 0:
            print(f"  {title}: n=0"); return
        tp = (q.outcome == "tp").sum(); sl = (q.outcome == "sl").sum()
        wr = 100 * tp / (tp + sl) if tp + sl else float("nan")
        print(f"  {title:22} n={n:5d} WR={wr:5.1f}%  "
              f"MEXC Σ{q.r_net_mexc.sum():+8.1f} avg={q.r_net_mexc.mean():+.4f}  "
              f"gross={q.gross.mean():+.4f}  "
              f"Bybit Σ{q.net_bybit.sum():+8.1f} avg={q.net_bybit.mean():+.4f}")

    for cfg, q in d.groupby("config"):
        print()
        print("=" * 90)
        print(cfg)
        blk("все", q)
        if "entry_kind" in q:
            blk("LIMIT", q[q.entry_kind == "LIMIT"])
            blk("MARKET", q[q.entry_kind == "MARKET"])
        early, late = q[q.year <= 2023], q[q.year >= 2024]
        blk("2020-23", early)
        blk("2024-26", late)
        print(f"  {'год':6} {'n':>5} {'WR':>6} {'avgMEXC':>8} {'ΣMEXC':>8} {'avgBybit':>9}")
        for y, yq in q.groupby("year"):
            tp = (yq.outcome == "tp").sum(); sl = (yq.outcome == "sl").sum()
            wr = 100 * tp / (tp + sl) if tp + sl else float("nan")
            print(f"  {y}  {len(yq):5d} {wr:5.1f}% {yq.r_net_mexc.mean():+8.4f} "
                  f"{yq.r_net_mexc.sum():+8.1f} {yq.net_bybit.mean():+9.4f}")
