"""Проверка: блокирует ли бэктест вторую сделку в одном HTF-окне (кросс-пар)."""
import pickle
from collections import Counter, defaultdict

base = r"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned"
for prof in ("tf7", "tf8"):
    all_htf = defaultdict(list)
    for sym in ("SOL", "ETH", "LTC", "KAS"):
        f = f"{base}/{sym}_{prof}_2024-01-01_2024-12-31.pkl"
        try:
            c = pickle.load(open(f, "rb"))
        except Exception as e:
            print(f"{sym} {prof}: нет кэша ({e})")
            continue
        for t in c.get("trades") or []:
            if t.get("entry_kind") != "LIMIT":
                continue
            ht = str(t.get("htf_time") or "")
            if ht:
                all_htf[ht].append(f"{sym}")
    multi = {k: v for k, v in all_htf.items() if len(v) > 1}
    print(f"\n=== {prof}: окон всего {len(all_htf)}, с ДВУМЯ+ сделками: {len(multi)} ===")
    for k, v in sorted(multi.items())[:6]:
        print(f"  {k}: {v}")
    cross = {k: v for k, v in multi.items() if len(set(v)) > 1}
    print(f"  из них кросс-пар (разные пары в одном окне): {len(cross)}")
    for k, v in sorted(cross.items())[:5]:
        print(f"    {k}: {v}")
