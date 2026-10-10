"""Контроль на второй паре: ETH tf8 2024 с текущей формулой (ceil5)."""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

logging.disable(logging.INFO)

from backtest.bot_aligned import run_bot_aligned_backtest

detect_filters = {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}

res = run_bot_aligned_backtest(
    since="2024-01-01", until="2024-12-31",
    profile="tf8", symbol="ETH",
    limit_bars=1, pos_bars=12,
    save=True, quiet=True,
    detect_filters=detect_filters,
)
tr = res.get("trades") or []
tot = sum(float(t.get("r_net") or 0) for t in tr)
lim = [t for t in tr if t.get("entry_kind") == "LIMIT"]
rlim = sum(float(t.get("r_net") or 0) for t in lim)
print(f"ETH tf8 2024 (ceil5): trades={len(tr)} LIMIT={len(lim)} sumR={tot:+.1f} sumR_lim={rlim:+.1f}", flush=True)
