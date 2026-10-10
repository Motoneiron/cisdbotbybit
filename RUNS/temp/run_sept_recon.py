"""Прогон MSS-конфига на сентябрьском окне (9-10 пар, Bybit 5m) + сводка живых.

Выход: live_recon/sept_recon_mss.pkl (trades+signals по всем парам).
"""
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

T = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp")
OUT = T / "live_recon"

live = json.load(open(OUT / "sept_tf7_trades.json", encoding="utf-8"))
print("живых сентябрьских tf7:", len(live))
print("kinds:", dict(Counter(v.get("entry_kind") for v in live)))
print("исходы:", dict(Counter(v.get("status") for v in live)))
print("пары:", dict(Counter(v.get("sym_guess") for v in live)))

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_t = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_t["fill_timeframe"] = "1m"
_t["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _t

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_TRY = ba._try_accept_signal


def _reset():
    ba._try_accept_signal = _ORIG_TRY


def _patch_tp1r():
    orig = ba._try_accept_signal
    def patched(sim, sig, tf, bar_i, *a, **kw):
        try:
            e, s = float(sig["entry"]), float(sig["stop"])
            if e > 0 and s > 0 and e != s:
                sig = {**sig, "tp": 2.0 * e - s}
        except Exception:
            pass
        return orig(sim, sig, tf, bar_i, *a, **kw)
    ba._try_accept_signal = patched


PAIRS = ["DOGE", "ETH", "LTC", "ADA", "KAS", "BNB", "SOL", "XRP", "LINK"]
rows_all, signals_all = [], []
t0 = time.time()
for p in PAIRS:
    csv = T / f"data_live_sep2026/{p}USDT_5m_bybit.csv"
    if not csv.exists():
        print("НЕТ:", csv)
        continue
    _reset()
    _patch_tp1r()
    from backtest.bot_aligned import run_bot_aligned_backtest
    try:
        res = run_bot_aligned_backtest(
            since="2026-09-01", until="2026-09-17", profile="tf7_main", symbol=p,
            csv=str(csv), limit_bars=2, pos_bars=144, detect_step=12, max_positions=5,
            ltf_fill=False, cancel_fib2=False, fee_model="bybit",
            entry_kind_mode="limit_only",
            detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True},
            save=False, quiet=True,
        )
    except Exception as e:
        print(f"{p}: FAIL {e!r}")
        continue
    tr = res.get("trades") or []
    sg = res.get("signals") or []
    for x in tr:
        x["_pair"] = p
    for x in sg:
        x["_pair"] = p
    rows_all += tr
    signals_all += sg
    print(f"{p}: trades={len(tr)} signals={len(sg)} sec={time.time()-t0:.0f}")

pickle.dump({"trades": rows_all, "signals": signals_all}, open(OUT / "sept_recon_mss.pkl", "wb"))
print(f"\nИТОГО: trades={len(rows_all)} signals={len(signals_all)} всего sec={time.time()-t0:.0f}")
print("written:", OUT / "sept_recon_mss.pkl")
