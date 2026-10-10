"""Смоук: один год SOL tf7 на починенном движке, A+V+D, lim10m."""
import sys
import time

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.bot_aligned import run_bot_aligned_backtest
from backtest.config import profile_to_runtime

print("runtime tf7/SOL:", profile_to_runtime("tf7", "SOL"))

t0 = time.time()
res = run_bot_aligned_backtest(
    since="2024-01-01",
    until="2024-12-31",
    profile="tf7",
    symbol="SOL",
    detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True},
    fee_model="mexc",
    max_positions=5,
    save=False,
    quiet=True,
)
print(f"\nsec={time.time()-t0:.0f}")
print("ключи:", sorted(res.keys()))
tr = res.get("trades") or []
print("сделок:", len(tr))
if tr:
    print("поля сделки:", sorted(tr[0].keys()))
    import collections
    print("kinds:", collections.Counter(t.get("entry_kind") for t in tr))
    print("outcomes:", collections.Counter(t.get("outcome") for t in tr))
    print("SumR:", round(sum(float(t["r_net"]) for t in tr), 2))
