"""live_filt_config.py — интегральная проверка конфигураций фильтров A/V/D (с busy, как в бою).

Прогоняет ЖИВУЮ модель (одна позиция, busy_until, htf_taken, tp_touched, min_stop 0.5%,
_sweep_valid_for_setup) с настраиваемыми фильтрами детекта:

  MODE=old: A=0.40 on, V on (max 2.5), D on (touches>=5, soft)   — текущий боевой конфиг
  MODE=new: A=0.80 on, V off, D off                               — реформа по итогам аудита

Запуск: python live_filt_config.py old   (или new)
Оба режима последовательно: python live_filt_config.py both
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

OUT_ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_cfg"
PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
}
YEARS = [
    (2024, "2024-01-01", "2025-01-01"),
    (2025, "2025-01-01", "2026-01-01"),
    (2026, "2026-01-01", "2026-09-01"),
]
WIN = 300
MAKER, TAKER = 0.00036, 0.0010

MODE_CONF = {
    "old": {"atr_enabled": True, "vol_enabled": True, "d_enabled": True},    # + min_sweep_atr=0.40
    "new": {"atr_enabled": True, "vol_enabled": False, "d_enabled": False},  # + min_sweep_atr=0.80
}
MODE_ATR_TH = {"old": 0.40, "new": 0.80}
MODE = "old"


def load_1m(path: str, since: str, until: str) -> pd.DataFrame:
    t0 = pd.Timestamp(since) - pd.Timedelta(days=4)
    t1 = pd.Timestamp(until) + pd.Timedelta(days=1)
    parts = []
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    for chunk in pd.read_csv(path, usecols=cols, chunksize=500_000):
        ot = pd.to_datetime(chunk["open_time"], unit="ms")
        m = (ot >= t0) & (ot < t1)
        if not m.any():
            if len(ot) and ot.iloc[-1] < t0:
                continue
            if len(ot) and ot.iloc[0] >= t1:
                break
            continue
        sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
        sub.index = ot[m]
        parts.append(sub)
    if not parts:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _outcome(df1, scan, direction, entry, stop, tp):
    t0 = pd.Timestamp(scan)
    window = df1[(df1.index >= t0) & (df1.index < t0 + pd.Timedelta(minutes=10))]
    fill_ts = None
    for ts, bar in window.iterrows():
        hit = float(bar.low) <= entry if direction == "LONG" else float(bar.high) >= entry
        if hit:
            fill_ts = ts
            break
    if fill_ts is None:
        return None
    end = fill_ts + pd.Timedelta(hours=12)
    path = df1[(df1.index >= fill_ts) & (df1.index <= end)]
    if path.empty:
        return None
    sp = abs(entry - stop) / entry
    exit_ts = path.index[-1]
    kind = "time"
    gross = None
    for ts, bar in path.iterrows():
        if direction == "LONG":
            sl_hit = float(bar.low) <= stop
            tp_hit = float(bar.high) >= tp
        else:
            sl_hit = float(bar.high) >= stop
            tp_hit = float(bar.low) <= tp
        if sl_hit:
            kind, gross, exit_ts = "sl", -1.0, ts
            break
        if tp_hit:
            kind, gross, exit_ts = "tp", 1.0, ts
            break
    if gross is None:
        last = float(path.iloc[-1].close)
        risk = (entry - stop) if direction == "LONG" else (stop - entry)
        gross = ((last - entry) if direction == "LONG" else (entry - last)) / risk
    fee_x = MAKER if kind == "tp" else TAKER
    r = float(gross) - MAKER / sp - fee_x / sp
    return kind, r, exit_ts


def _tp_touched(sl, direction, tp, since) -> bool:
    if tp <= 0 or not since:
        return False
    try:
        t = pd.Timestamp(since)
    except Exception:
        return False
    sub = sl[sl.index >= t]
    if len(sub) < 2:
        sub = sub.iloc[:-1] if len(sub) else sub
    else:
        sub = sub.iloc[:-1]
    if sub.empty:
        return False
    if direction == "LONG":
        return float(sub["high"].max()) >= tp
    return float(sub["low"].min()) <= tp


def walk(bot, sym, df5, df1, since, until) -> list[dict]:
    bot.state.paper = True
    bot.state.sweep_candidates.clear()
    bot.state.htf_sweep_lock.clear()
    if hasattr(bot.state, "htf_sweep_validated"):
        bot.state.htf_sweep_validated.clear()
    seen: set = set()
    htf_taken: set = set()
    busy_until = None
    htf = int(bot.CONFIG["tf7"]["htf_ratio"])
    t_since = pd.Timestamp(since)
    t_until = pd.Timestamp(until)
    rows = []
    n = len(df5)
    t0 = time.time()
    atr_th = MODE_ATR_TH[MODE]
    for i in range(WIN, n):
        scan_ts = pd.Timestamp(df5.index[i])
        if scan_ts < t_since:
            continue
        if scan_ts >= t_until:
            break
        if i % 8000 == 0:
            print(f"  [{MODE}] {sym} {scan_ts.date()} trades={len(rows)} sec={time.time()-t0:.0f}", flush=True)
        sl = df5.iloc[i - (WIN - 1) : i + 1]
        sigs = bot.detect_signals(
            sl, seen, htf_ratio=htf, tf_name="tf7",
            df_confirm=None, min_sweep_atr=atr_th,
        ) or []
        sigs.sort(key=lambda s: str(s.get("timestamp") or ""), reverse=True)
        scan_s = str(scan_ts)[:19]
        for s in sigs:
            h = str(s.get("hash") or "")
            if h and h not in seen:
                seen.add(h)
            direction = str(s.get("direction") or "")
            try:
                entry = float(s.get("entry") or 0)
                stop = float(s.get("stop") or 0)
                tp = float(s.get("tp") or 0)
            except (TypeError, ValueError):
                continue
            if entry <= 0 or stop <= 0 or entry == stop:
                continue
            if abs(stop - entry) / entry * 100.0 < 0.5:
                continue
            htf_s = str(s.get("htf_time") or "")[:19]
            ok_sw, _why = bot._sweep_valid_for_setup(
                sl, htf, htf_s,
                str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or ""),
                float(s.get("htf_sweep_level") or s.get("sweep_level") or 0),
                direction,
            )
            if not ok_sw:
                continue
            since_tp = str(s.get("confirm_bar_time") or s.get("trigger_bar_time") or "")
            if _tp_touched(sl, direction, tp, since_tp):
                if htf_s:
                    htf_taken.add(htf_s)
                continue
            if htf_s and htf_s in htf_taken:
                continue
            if busy_until is not None and scan_ts < busy_until:
                seen.add(h)
                continue
            if htf_s:
                htf_taken.add(htf_s)
            got = _outcome(df1, scan_s, direction, entry, stop, tp)
            if got is None:
                continue
            kind, r, exit_ts = got
            busy_until = pd.Timestamp(exit_ts)
            rows.append({
                "sym": sym,
                "direction": direction,
                "outcome": kind,
                "r": r,
                "scan": scan_s,
                "cbt": str(s.get("confirm_bar_time") or "")[:19],
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "sp": abs(entry - stop) / entry,
            })
    return rows


def run_symbol(sym: str) -> str:
    sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
    logging.disable(logging.CRITICAL)
    import cisdbot as bot

    bot.CONFIG["tf7"]["detect_filters"] = dict(MODE_CONF[MODE])
    out = os.path.join(OUT_ROOT, MODE)
    os.makedirs(out, exist_ok=True)
    msgs = []
    for year, since, until in YEARS:
        dst = os.path.join(out, f"{sym}_{year}.pkl")
        if os.path.exists(dst):
            msgs.append(f"skip {sym} {year}")
            continue
        t0 = time.time()
        df1 = load_1m(PATHS[sym], since, until)
        if df1.empty:
            msgs.append(f"EMPTY {sym} {year}")
            continue
        df5 = bot._resample_ohlcv(df1, "5m")
        rows = walk(bot, sym, df5, df1, since, until)
        with open(dst + ".tmp", "wb") as f:
            pickle.dump(rows, f)
        os.replace(dst + ".tmp", dst)
        msgs.append(f"OK {sym} {year} n={len(rows)} sec={time.time()-t0:.0f}")
        print(msgs[-1], flush=True)
    return " | ".join(msgs)


def main():
    global MODE
    mode_arg = (sys.argv[1] if len(sys.argv) > 1 else "old").lower()
    modes = ["old", "new"] if mode_arg == "both" else [mode_arg]
    for m in modes:
        MODE = m
        print(f"===== MODE={m} conf={MODE_CONF[m]} atr_th={MODE_ATR_TH[m]} =====", flush=True)
        with Pool(6, initializer=_init_mode, initargs=(m,)) as pool:
            for msg in pool.imap_unordered(_run_symbol_wrap, list(PATHS)):
                print(msg, flush=True)


def _init_mode(m: str):
    global MODE
    MODE = m


def _run_symbol_wrap(sym: str) -> str:
    return run_symbol(sym)


if __name__ == "__main__":
    main()
