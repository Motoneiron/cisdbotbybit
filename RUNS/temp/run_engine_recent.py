"""Прогон бэк-движка на 14–18.09.2026 по свежим 5m-данным Bybit (RUNS/temp/data_recent).
Исходные датасеты не трогаем: подменяем ссылку на 5m-датасет в backtest.data.
Профиль tf8 (30m → 8H), лимитка 1 бар (30 мин), позиция 12 баров (6ч) — как в живом боте.
"""
import json
import pickle
import sys
from pathlib import Path

REC = Path("D:/PYTHON/cisdbotbybit/RUNS/temp/data_recent")
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]

sys.path.insert(0, "D:/PYTHON/CISDBOT")
import logging  # noqa: E402

logging.disable(logging.INFO)

import backtest.data as D  # noqa: E402

D.DATA_ROOTS["recent"] = REC
for s in PAIRS:
    D.DATASETS.setdefault(s, {})["5m"] = ("recent", f"{s}USDT_5m_recent.csv")

from backtest.bot_aligned import run_bot_aligned_backtest  # noqa: E402

out = {}
for sym in PAIRS:
    try:
        res = run_bot_aligned_backtest(
            since="2026-08-20", until="2026-09-18",
            profile="tf8", symbol=sym,
            limit_bars=1, pos_bars=12,
            save=False, quiet=True,
            detect_filters={"atr_enabled": False, "vol_enabled": False, "d_enabled": False},
        )
        out[sym] = {"signals": res.get("signals") or [], "trades": res.get("trades") or []}
        print(f"{sym}: сигналов {len(out[sym]['signals'])}, сделок {len(out[sym]['trades'])}")
    except Exception as e:
        print(f"{sym}: FAIL {e!r}")
        out[sym] = {"signals": [], "trades": []}

with open("D:/PYTHON/cisdbotbybit/RUNS/temp/bt_recent_tf8.pkl", "wb") as f:
    pickle.dump(out, f)

print()
print("=== сетапы бэктеста tf8, триггер 15–17.09 ===")
import pandas as pd  # noqa: E402

rows = []
for sym, d in out.items():
    tr = {str(t.get("hash")): t for t in d["trades"]}
    for s in d["signals"]:
        ts = pd.to_datetime(str(s.get("trigger_bar_time")), errors="coerce")
        if pd.isna(ts) or not (pd.Timestamp("2026-09-15") <= ts <= pd.Timestamp("2026-09-18")):
            continue
        t = tr.get(str(s.get("hash"))) or {}
        rows.append((str(ts)[:16], sym, s.get("direction"), str(s.get("htf_time"))[:16],
                     s.get("entry"), s.get("stop"), s.get("tp"), s.get("htf_sweep_level"),
                     t.get("outcome"), t.get("r_net"), t.get("entry_bar"), t.get("exit_bar")))
rows.sort()
print("всего:", len(rows))
for r in rows:
    rr = f"{r[9]:+.3f}" if isinstance(r[9], float) else str(r[9])
    print(f"  {r[0]}  {r[1]:5s} {r[2]:5s} htf {r[3]}  entry {r[4]}  stop {r[5]}  sweep {r[7]}  | {r[8]} {rr} bars {r[10]}→{r[11]}")
