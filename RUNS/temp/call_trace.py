"""call_trace.py — все вызовы detect_signals внутри канонного прогона + контрольный вызов вне его.

Цель: понять, почему канон 'не видит' сигнал 01-01 11:20, который виден при прямом вызове.
"""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

logging.disable(logging.CRITICAL)

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_tf7_main = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7_main["fill_timeframe"] = "1m"
_tf7_main["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _tf7_main

import backtest.bot_aligned as ba  # noqa: E402
import cisdbot as bot  # noqa: E402

# ---------- контрольный вызов вне прогона (как probe) ----------
import pandas as pd  # noqa: E402

df_all = pd.read_csv(
    r"D:/databtcusdt/SOLUSDT-5m/SOLUSDT_5m_full_hdr.csv",
    usecols=["open_time", "open", "high", "low", "close", "volume"],
)
df_all.index = pd.to_datetime(df_all.pop("open_time"), unit="ms")
df_all = df_all.astype(float).sort_index()

i = int(df_all.index.searchsorted(pd.Timestamp("2024-01-01 11:20:00")))
sl = df_all.iloc[i - 199 : i + 1]
ctrl = bot.detect_signals(
    sl, set(), htf_ratio=int(bot.CONFIG["tf7"]["htf_ratio"]), tf_name="tf7", df_confirm=None
)
print(f"[CONTROL] вне прогона, бар {df_all.index[i]}, на чистом state: {len(ctrl or [])} сигналов")
for s in ctrl or []:
    print(f"   {s.get('direction')} cbt={s.get('confirm_bar_time')} e={s.get('entry')}", flush=True)

# ---------- трассировка вызовов внутри прогона ----------
_ORIG = bot.detect_signals


def det2(df_win, seen_arg, *a, **kw):
    st = bot.state
    sc_pre = len(getattr(st, "sweep_candidates", None) or {})
    pos = len(getattr(st, "positions", None) or [])
    pend = len(getattr(st, "pending_limits", None) or [])
    seen_n = len(seen_arg or set())
    out = _ORIG(df_win, seen_arg, *a, **kw)
    n = len(out) if out else 0
    s = ""
    if out:
        for x in out:
            s += f"  [{x.get('direction')} cbt={x.get('confirm_bar_time')} e={x.get('entry')} fib={1 if x.get('fib_stretch_market') else 0}]"
    print(
        f"[CALL] win_end={df_win.index[-1]} bars={len(df_win)} seen={seen_n} sw_cand={sc_pre} pos={pos} pend={pend} -> {n}{s}",
        flush=True,
    )
    return out


bot.detect_signals = det2

res = ba.run_bot_aligned_backtest(
    since="2024-01-01",
    until="2024-01-03",
    profile="tf7_main",
    symbol="SOL",
    limit_bars=2,
    pos_bars=144,
    htf_ratio=None,
    detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True},
    fee_model="mexc",
    max_positions=5,
    entry_kind_mode="limit_only",
    market_fill_mode="signal_ref",
    cancel_fib2=False,
    save=False,
    quiet=True,
)
print("=== TRADES:", len(res.get("trades") or []))
