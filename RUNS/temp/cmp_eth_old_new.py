"""ETH old vs ceil5 сверка."""
import pickle

old_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/ETH_tf8_2024-01-01_2024-12-31.pkl"
new_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-13/bot_aligned/ETH_tf8_2024-01-01_2024-12-31.pkl"

for label, f in (("old", old_f), ("ceil5", new_f)):
    c = pickle.load(open(f, "rb"))
    tr = c.get("trades") or []
    lim = [t for t in tr if t.get("entry_kind") == "LIMIT"]
    print(f"{label}: всего={len(tr)} LIMIT={len(lim)} "
          f"sumR_lim={sum(float(t.get('r_net') or 0) for t in lim):+.1f} "
          f"sumR_all={sum(float(t.get('r_net') or 0) for t in tr):+.1f}")
    print(f"   TP={sum(1 for t in lim if t['outcome']=='tp')} SL={sum(1 for t in lim if t['outcome']=='sl')} "
          f"TIME={sum(1 for t in lim if t['outcome']=='time')}")
