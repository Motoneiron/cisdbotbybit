"""Тайминг-тест движка: один прогон (ADA tf7 2023) с filters-off, save=False."""
import logging
import sys
import time

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

logging.disable(logging.INFO)

from backtest.bot_aligned import run_bot_aligned_backtest

t0 = time.time()
res = run_bot_aligned_backtest(
    since="2023-01-01", until="2023-12-31",
    profile="tf7", symbol="ADA",
    limit_bars=4, pos_bars=192,
    save=False, quiet=True,
    detect_filters={"atr_enabled": False, "vol_enabled": False, "d_enabled": False},
)
dt = time.time() - t0
print("keys:", list(res.keys()))
trades = res.get("trades") or []
sigs = res.get("signals") or []
print("trades:", len(trades), "signals:", len(sigs), "sec:", round(dt, 1))
if sigs:
    keys = set(sigs[0].keys())
    print("has prior_touches:", "prior_touches" in keys, "| quality_score:", "quality_score" in keys,
          "| detect_filters:", sigs[0].get("detect_filters"))
if trades:
    print("sample trade:", {k: str(trades[0].get(k))[:40] for k in ("hash", "entry_kind", "direction", "entry_px", "stop")})
