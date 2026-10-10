"""Сверка bot-aligned с живым журналом 22-25 сент: шаг 1, A+V+D, стоп >= 0.5%."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_sep"
PAIRS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_tf7_main = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7_main["fill_timeframe"] = "1m"
_tf7_main["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _tf7_main

import backtest.bot_aligned as ba  # noqa: E402

AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}


def fetch_pair(sym: str) -> str:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{sym}USDT_1m.csv")
    start = int(datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = []
    cur = start
    while cur < end:
        url = (
            "https://api.bybit.com/v5/market/kline?category=linear"
            f"&symbol={sym}USDT&interval=1&start={cur}&limit=1000"
        )
        payload = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    payload = json.loads(resp.read().decode())
            except Exception:
                time.sleep(1.0 + attempt)
                continue
            if payload.get("retCode") == 0:
                break
            time.sleep(1.0 + attempt)
        if not payload or payload.get("retCode") != 0:
            raise RuntimeError(payload)
        batch = list(reversed(payload["result"]["list"]))
        if not batch:
            break
        rows.extend(batch)
        last = int(batch[-1][0])
        nxt = last + 60_000
        if nxt <= cur:
            break
        cur = nxt
        if len(batch) < 1000:
            break
        time.sleep(0.12)
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
    df = df.drop_duplicates("open_time").sort_values("open_time")
    df["timestamp"] = pd.to_datetime(df["open_time"].astype(np.int64), unit="ms", utc=True).dt.tz_convert(None)
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    df[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(path, index=False)
    print(f"fetched {sym} {len(df)} {df.timestamp.iloc[0]} .. {df.timestamp.iloc[-1]}", flush=True)
    return path


def _install():
    if getattr(ba, "_match_installed", False):
        return
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
    ba._match_installed = True


def min_stop_gate(sig, bar_i=None, df=None, df_win=None, sim=None):
    try:
        e, s = float(sig["entry"]), float(sig["stop"])
    except (TypeError, ValueError, KeyError):
        return False
    if e <= 0 or s <= 0 or e == s:
        return False
    return abs(s - e) / e * 100.0 >= 0.5


def one(sym: str):
    _install()
    csv = os.path.join(OUT, f"{sym}USDT_1m.csv")
    from backtest.bot_aligned import run_bot_aligned_backtest

    res = run_bot_aligned_backtest(
        since="2026-09-22", until="2026-09-25", profile="tf7_main", symbol=sym, csv=csv,
        limit_bars=2, pos_bars=144, htf_ratio=240, detect_step=1,
        detect_filters=AVD, fee_model="bybit", max_positions=7,
        entry_kind_mode="limit_only", market_fill_mode="signal_ref",
        cancel_fib2=False, mss_on_ltf=False, save=False, quiet=True,
        hooks={"accept_gate": min_stop_gate},
    )
    sigs = []
    for s in res.get("signals") or []:
        sigs.append({
            "sym": sym,
            "direction": s.get("direction"),
            "entry": float(s.get("entry") or 0),
            "stop": float(s.get("stop") or 0),
            "tp": float(s.get("tp") or 0),
            "htf": str(s.get("htf_time") or "")[:19],
            "ts": str(s.get("timestamp") or "")[:19],
            "status": s.get("pending_status"),
            "hash": s.get("hash"),
        })
    trades = []
    for t in res.get("trades") or []:
        trades.append({
            "sym": sym,
            "direction": t.get("direction"),
            "entry": float(t.get("entry_px") or t.get("entry") or 0),
            "stop": float(t.get("stop") or 0),
            "outcome": t.get("outcome"),
            "r": float(t.get("r_net") or 0),
            "hash": t.get("hash"),
            "entry_ts": str(t.get("entry_ts") or ""),
            "exit_ts": str(t.get("exit_ts") or ""),
        })
    print(f"{sym} signals={len(sigs)} trades={len(trades)}", flush=True)
    return sigs, trades


def main():
    for sym in PAIRS:
        fetch_pair(sym)
    sigs, trades = [], []
    for sym in PAIRS:
        s, t = one(sym)
        sigs.extend(s)
        trades.extend(t)
    print("\n=== SIGNALS ===")
    for s in sorted(sigs, key=lambda x: (x["ts"], x["sym"])):
        print(
            f"{s['ts']} {s['sym']:4} {s['direction']:5} entry={s['entry']} "
            f"stop={s['stop']} tp={s['tp']} htf={s['htf']} {s['status']}"
        )
    print("\n=== TRADES ===")
    for t in trades:
        print(
            f"{t['sym']:4} {t['direction']:5} {t['outcome']:4} r={t['r']:+.3f} "
            f"entry={t['entry']} stop={t['stop']} in={t['entry_ts']} out={t['exit_ts']}"
        )


if __name__ == "__main__":
    main()
