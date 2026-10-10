"""Проверка фикса движка: SOL tf7/tf8 2024 с новым честным fill."""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

logging.disable(logging.INFO)

from backtest.bot_aligned import run_bot_aligned_backtest

detect_filters = {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}

for profile, lb, pb in (("tf7", 4, 192), ("tf8", 1, 12)):
    res = run_bot_aligned_backtest(
        since="2024-01-01", until="2024-12-31",
        profile=profile, symbol="SOL",
        limit_bars=lb, pos_bars=pb,
        save=True, quiet=True,
        detect_filters=detect_filters,
    )
    tr = res.get("trades") or []
    tot = sum(float(t.get("r_net") or 0) for t in tr)
    print(f"SOL {profile} 2024 (новый движок): trades={len(tr)} sumR={tot:+.1f}", flush=True)
