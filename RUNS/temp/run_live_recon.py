"""Сверочные прогоны на окне живых сделок SOL tf7 (2026-06-23..08-16).

Данные: live_recon/SOLUSDT_1m_recon.csv (движок сам ресемплит 5m; '1m' в имени).
Конфиги:
  LIVE_EMUL — эмуляция живого стека: detect A+D (vol off), LIMIT+MARKET,
              лимитка 10м, поз 12ч, TP=фибо (без tp-патча), detect_step=1.
  CORE_C5   — наш чистый стек: A+V+D, LIMIT-only, TP=1R, detect_step=12.
Выход: live_recon/recon_{cfg}.pkl (trades, signals) + печать ключей res.
"""
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon"
CSV = "D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon/SOLUSDT_1m_recon.csv"
SINCE, UNTIL = "2026-06-22", "2026-08-22"

import backtest.config as _cfgm  # noqa: E402

_tf7 = dict(_cfgm.BOT_TF_PROFILES["tf7"])
_tf7m = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7m["fill_timeframe"] = "1m"
_tf7m["label"] = "5m -> 4H main-mss"
_cfgm.BOT_TF_PROFILES["tf7_main"] = _tf7m

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_FILL = ba._fill_from_after_confirm_close
_ORIG_TRY = ba._try_accept_signal


def _reset_patches():
    ba._fill_from_after_confirm_close = _ORIG_FILL
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


def run_cfg(name):
    dst = f"{OUT}/recon_{name}.pkl"
    if os.path.exists(dst):
        print(f"skip {name}")
        return
    _reset_patches()
    kw = {}
    prof = "tf7"
    if name == "CORE_C5":
        _patch_tp1r()
        kw = dict(detect_step=12, entry_kind_mode="limit_only",
                  detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True})
    elif name == "MSS_MAIN":
        _patch_tp1r()
        prof = "tf7_main"
        kw = dict(detect_step=12, entry_kind_mode="limit_only",
                  detect_filters={"atr_enabled": True, "vol_enabled": True, "d_enabled": True})
    else:  # LIVE_EMUL
        kw = dict(detect_step=1, entry_kind_mode="all",
                  detect_filters={"atr_enabled": True, "vol_enabled": False, "d_enabled": True})
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest
    res = run_bot_aligned_backtest(
        since=SINCE, until=UNTIL, profile=prof, symbol="SOL",
        csv=CSV, limit_bars=2, pos_bars=144,
        max_positions=5, cancel_fib2=False, fee_model="mexc",
        save=False, quiet=False, **kw,
    )
    keys = sorted(res.keys())
    print(f"[{name}] res keys: {keys}")
    keep = {}
    for k, v in res.items():
        if k in ("trades",):
            keep[k] = v
        elif isinstance(v, (int, float, str, bool, dict, list)) and k != "df":
            try:
                pickle.dumps(v)
                keep[k] = v
            except Exception:
                pass
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(keep, f)
    os.replace(dst + ".tmp", dst)
    n_tr = len(keep.get("trades") or [])
    sig = keep.get("signals")
    n_sig = len(sig) if isinstance(sig, list) else "—"
    print(f"[{name}] trades={n_tr} signals={n_sig} sec={time.time()-t0:.0f}")


if __name__ == "__main__":
    for nm in (sys.argv[1:] or ["LIVE_EMUL", "CORE_C5"]):
        run_cfg(nm)
    print("DONE")
