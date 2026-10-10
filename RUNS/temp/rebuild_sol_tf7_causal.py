"""Пересчёт SOL tf7 lim10m на текущем движке (causal fill после close конфирм-бара).

Варианты:
  both          — sw+vol, как старый кэш 3350/+1169 (MEXC, fib TP)
  dhybrid       — sw+vol+D, книга 2883/+1195
  *_scan_close  — то же, MARKET fill = close 5m scan-бара + slippage

Не перезаписывает старый кэш. Пишет в RUNS/temp/sol_tf7_causal/.
"""
from __future__ import annotations

import contextlib
import io
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(r"D:/PYTHON/CISDBOT")
sys.path.insert(0, str(ROOT))

from backtest.bot_aligned import run_bot_aligned_backtest  # noqa: E402

FILTER_VARIANTS = {
    "both": {
        "label": "sw+vol (research default)",
        "sw_atr_min": 0.40,
        "trigger_vol_max": 2.5,
        "disable_sweep": False,
        "disable_vol": False,
        "d_enabled": False,
    },
    "dhybrid": {
        "label": "sw+vol+D soft-DOW hybrid",
        "sw_atr_min": 0.40,
        "trigger_vol_max": 2.5,
        "disable_sweep": False,
        "disable_vol": False,
        "d_enabled": True,
    },
}

PERIODS = [
    ("2020-09-14", "2020-12-31"),
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
    ("2026-01-01", "2026-06-23"),
]

OUT = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/sol_tf7_causal")
SW_DEFAULT, VOL_DEFAULT = 0.40, 2.5


def patch_detect(fv: dict):
    import cisdbot as bot

    old_sw, old_vol = dict(bot.SWEEP_ATR_FILTER), dict(bot.TRIGGER_VOL_FILTER)

    @contextlib.contextmanager
    def _cm():
        try:
            bot.SWEEP_ATR_FILTER["min_atr"] = 0.0 if fv["disable_sweep"] else SW_DEFAULT
            bot.TRIGGER_VOL_FILTER["max_ratio"] = 0.0 if fv["disable_vol"] else VOL_DEFAULT
            yield
        finally:
            bot.SWEEP_ATR_FILTER.clear(); bot.SWEEP_ATR_FILTER.update(old_sw)
            bot.TRIGGER_VOL_FILTER.clear(); bot.TRIGGER_VOL_FILTER.update(old_vol)

    return _cm()


def summarize(trades: list) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "tp": 0, "sl": 0, "other": 0, "wr": None, "sum_r": 0.0, "avg": None}
    tp = sum(1 for t in trades if t.get("outcome") == "tp")
    sl = sum(1 for t in trades if t.get("outcome") == "sl")
    other = n - tp - sl
    sum_r = float(sum(float(t.get("r_net") or 0) for t in trades))
    decided = tp + sl
    return {
        "n": n, "tp": tp, "sl": sl, "other": other,
        "wr": round(100.0 * tp / decided, 2) if decided else None,
        "sum_r": round(sum_r, 3),
        "avg": round(sum_r / n, 4) if n else None,
    }


def run_one(since: str, until: str, fv: dict, market_fill_mode: str) -> dict:
    detect_filters = {
        "atr_enabled": not bool(fv["disable_sweep"]),
        "vol_enabled": not bool(fv["disable_vol"]),
        "d_enabled": bool(fv.get("d_enabled", False)),
        "kama_enabled": False,
    }
    buf = io.StringIO()
    with patch_detect(fv), contextlib.redirect_stdout(buf):
        r = run_bot_aligned_backtest(
            since=since,
            until=until,
            profile="tf7",
            symbol="SOL",
            pos_bars=144,
            limit_bars=2,
            entry_policy="bot",
            fee_model="mexc",
            cancel_fib2=True,
            save=False,
            quiet=True,
            detect_filters=detect_filters,
            market_fill_mode=market_fill_mode,
        )
    payload = {
        "trades": r["trades"],
        "signals": r.get("signals") or [],
        "since": since,
        "until": until,
        "profile": "tf7",
        "symbol": "SOL",
        "limit_bars": 2,
        "pos_bars": 144,
        "fee_model": "mexc",
        "cancel_fib2": True,
        "market_fill_mode": market_fill_mode,
        "sw_atr_min": fv["sw_atr_min"],
        "trigger_vol_max": fv["trigger_vol_max"],
        "d_enabled": bool(fv.get("d_enabled")),
        "filter_label": fv["label"],
        "metrics": summarize(r["trades"]),
    }
    return payload


JOBS = [
    ("both", FILTER_VARIANTS["both"], "signal_ref"),
    ("dhybrid", FILTER_VARIANTS["dhybrid"], "signal_ref"),
    ("both_scan_close", FILTER_VARIANTS["both"], "scan_close"),
    ("dhybrid_scan_close", FILTER_VARIANTS["dhybrid"], "scan_close"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n_jobs = len(JOBS) * len(PERIODS)
    done = 0
    print(f"jobs={n_jobs} out={OUT}", flush=True)
    for tag, fv, mfill in JOBS:
        for since, until in PERIODS:
            done += 1
            dst = OUT / f"SOL_tf7_{since}_{until}_{tag}.pkl"
            if dst.exists():
                c = pickle.load(open(dst, "rb"))
                m = c.get("metrics") or summarize(c.get("trades") or [])
                print(f"[{done}/{n_jobs}] skip {tag} {since} {m}", flush=True)
                continue
            t1 = time.time()
            payload = run_one(since, until, fv, mfill)
            tmp = dst.with_suffix(".pkl.tmp")
            pickle.dump(payload, open(tmp, "wb"))
            os.replace(tmp, dst)
            m = payload["metrics"]
            print(
                f"[{done}/{n_jobs}] +{time.time()-t0:.0f}s {tag} {since} "
                f"n={m['n']} WR={m['wr']} SumR={m['sum_r']} sec={time.time()-t1:.0f}",
                flush=True,
            )
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
