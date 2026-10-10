"""Сравнение старый (до фикса) vs новый (после фикса) кэш SOL tf8 2024."""
import pickle

import pandas as pd

old_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/SOL_tf8_2024-01-01_2024-12-31.pkl"
new_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned/SOL_tf8_2024-01-01_2024-12-31.pkl"

for label, f in (("СТАРЫЙ (до фикса)", old_f), ("НОВЫЙ (фикс)", new_f)):
    c = pickle.load(open(f, "rb"))
    trades = c.get("trades") or []
    lim = [t for t in trades if t.get("entry_kind") == "LIMIT"]
    mkt = [t for t in trades if t.get("entry_kind") != "LIMIT"]
    r_lim = sum(float(t.get("r_net") or 0) for t in lim)
    r_all = sum(float(t.get("r_net") or 0) for t in trades)
    tp = sum(1 for t in lim if t["outcome"] == "tp")
    sl = sum(1 for t in lim if t["outcome"] == "sl")
    # сколько с entry_bar < created_bar
    fake = sum(1 for t in lim if t["entry_bar"] < t["created_bar"])
    same = sum(1 for t in lim if t["entry_bar"] == t["created_bar"])
    later = sum(1 for t in lim if t["entry_bar"] > t["created_bar"])
    print(f"=== {label} ===")
    print(f"  всего: {len(trades)} | LIMIT: {len(lim)} | MARKET: {len(mkt)}")
    print(f"  LIMIT: TP={tp} SL={sl} sumR(lim)={r_lim:+.1f} | sumR(all)={r_all:+.1f}")
    print(f"  entry_bar vs created_bar: раньше={fake}, ровно={same}, позже={later}")
    print()
