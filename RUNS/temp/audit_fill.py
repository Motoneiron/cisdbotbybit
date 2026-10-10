"""Чистая проверка fill-якоря tf7 (SOL 2024): old vs causal, изолированные процессы.

Проблема: в sol_tf7_matrix.py патч old_fill применялся в воркере навсегда — если
воркеры начали с C1-задач, c2..c5 могли считаться С ПАТЧЕМ (протечка). Этот скрипт
запускает каждый режим в СВЕЖЕМ процессе (один прогон = один процесс), без протечек.

Запуск: python audit_fill.py old   |   python audit_fill.py causal
"""
import logging
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

mode = sys.argv[1].lower()
assert mode in ("old", "causal")

if mode == "old":
    import pandas as pd
    import backtest.bot_aligned as ba

    def old_fill(cbt_ts, confirm_min):
        return pd.Timestamp(cbt_ts) + pd.Timedelta(minutes=int(confirm_min))

    ba._fill_from_after_confirm_close = old_fill

logging.disable(logging.INFO)
from backtest.bot_aligned import run_bot_aligned_backtest  # noqa: E402

t0 = time.time()
res = run_bot_aligned_backtest(
    since="2024-01-01", until="2024-12-31",
    profile="tf7", symbol="SOL",
    detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True},
    fee_model="mexc", max_positions=5,
    entry_kind_mode="all", market_fill_mode="signal_ref", cancel_fib2=None,
    save=False, quiet=True,
)
trades = res.get("trades") or []
n = len(trades)
s = sum(float(t.get("r_net") or 0) for t in trades)
hashes = sorted(str(t.get("hash")) for t in trades)
print(f"[{mode}] n={n} SumR={s:+.1f} sec={time.time()-t0:.0f}")
pickle.dump({"mode": mode, "n": n, "sum": s, "hashes": hashes},
            open(f"D:/PYTHON/cisdbotbybit/RUNS/temp/audit_fill_{mode}.pkl", "wb"))
