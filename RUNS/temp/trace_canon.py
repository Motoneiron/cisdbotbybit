"""Трассировка канона (ABL_MSS_MAIN-конфиг): что канон видит/делает с сигналами. Январь 2024, SOL."""
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

_BASE_TRY = ba._try_accept_signal
_ORIG_DET = bot.detect_signals
_ORIG_OPEN = ba._open_position


def _stamp(trade, df=None, sim=None):
    try:
        if df is not None:
            for k, ik in (("created_ts", "created_bar"), ("entry_ts", "entry_bar"), ("exit_ts", "exit_bar")):
                ib = trade.get(ik)
                if ib is not None:
                    trade[k] = str(df.index[int(ib)])
    except Exception:
        pass


def det_trace(df_win, *a, **kw):
    out = _ORIG_DET(df_win, *a, **kw)
    if out:
        scan = str(df_win.index[-1])
        for s in out:
            print(f"[DET ] scan={scan} {str(s.get('hash') or '')[:12]} {s.get('direction')} "
                  f"cbt={s.get('confirm_bar_time')} swc={s.get('sweep_close_bar_time')} e={s.get('entry')}", flush=True)
    return out


def try_trace(sim, sig, tf, bar_i, *a, **kw):
    # TP=1R (как в tf7_ablations)
    try:
        e, s0 = float(sig["entry"]), float(sig["stop"])
        if e > 0 and s0 > 0 and e != s0:
            sig = {**sig, "tp": 2.0 * e - s0}
    except Exception:
        pass
    df = a[2] if len(a) > 2 else None
    bt = str(df.index[bar_i]) if df is not None else "?"
    h = str(sig.get("hash") or "")[:12]
    d = str(sig.get("direction"))
    cbt = str(sig.get("confirm_bar_time") or "")
    swc = str(sig.get("sweep_close_bar_time") or "")
    res = _BASE_TRY(sim, sig, tf, bar_i, *a, **kw)
    if res is None:
        try:
            sig_htf = bot._htf_time_for_sig(sig, tf)
            diag = (
                f"slots={ba._open_slots(sim)} htf={ba._htf_slot_taken(sim, tf, sig_htf)} "
                f"pend={ba._has_pending_htf(sim, tf, d, sig_htf)} "
                f"dup={ba._duplicate_nearby(sim, sig, tf)} opp={ba._has_opposite_open(sim, d)}"
            )
        except Exception as exc:
            diag = f"diag_err={exc!r}"
        try:
            kind_r, _pref = ba._resolve_entry(sig, entry_policy=kw.get("entry_policy") or "bot")
        except Exception as exc:
            kind_r = f"err:{exc!r}"
        try:
            st, why = bot._sig_sweep_fib1_stretched(sig)
            ex = f"fib1stretch={st}" + (f" | {why}" if st else "")
        except Exception as exc:
            ex = f"fib1_err={exc!r}"
        print(f"[TRY ] scan={bt} {h} {d} cbt={cbt} swc={swc} e={sig.get('entry')} -> REJECT {diag} kind={kind_r} {ex}", flush=True)
    else:
        print(f"[TRY ] scan={bt} {h} {d} cbt={cbt} swc={swc} e={sig.get('entry')} -> ACCEPT "
              f"fft={getattr(res, 'fill_from_ts', None)} exp={getattr(res, 'expire_ts', None)}", flush=True)
    return res


def open_trace(sim, pl, entry_bar, entry_px):
    print(f"[FILL] {str(getattr(pl, 'sig_hash', '') or '')[:12]} {getattr(pl, 'direction', '')} "
          f"px={entry_px} bar={entry_bar}", flush=True)
    return _ORIG_OPEN(sim, pl, entry_bar, entry_px)


ba._try_accept_signal = try_trace
bot.detect_signals = det_trace
ba._open_position = open_trace

res = ba.run_bot_aligned_backtest(
    since="2024-01-01", until="2024-02-01", profile="tf7_main", symbol="SOL",
    limit_bars=2, pos_bars=144, htf_ratio=None,
    detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True},
    fee_model="mexc", max_positions=5, entry_kind_mode="limit_only",
    market_fill_mode="signal_ref", cancel_fib2=False, save=False, quiet=True,
    hooks={"on_close": _stamp},
)
print("=== TRADES ===", flush=True)
for t in res.get("trades") or []:
    print("  ", t.get("created_ts"), "->", t.get("entry_ts"), t.get("direction"),
          t.get("outcome"), str(t.get("hash") or "")[:12], flush=True)
print("total:", len(res.get("trades") or []), flush=True)
print("done", flush=True)
