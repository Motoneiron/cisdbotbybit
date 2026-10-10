"""live_filt_death.py — вход как база (1-й бар сигнала), но с трекингом «смерти структуры»:
если сигнал (cbt,dir) больше не выдаётся детектом N баров подряд — фиксируем R выхода
на этом баре (правило early-exit, применяется post-hoc).

Прогон считает базу (полный исход как live_filt) + метки смертей для N=1,2,3.
Запуск: python live_filt_death.py [SYM ...]   (по умолчанию все пары)
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import time
from multiprocessing import Pool

import pandas as pd

OUT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_death"
PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
}
WIN = 300
MAKER, TAKER = 0.00036, 0.0010
YEARS = {
    2024: ("2024-01-01", "2025-01-01"),
    2025: ("2025-01-01", "2026-01-01"),
    2026: ("2026-01-01", "2027-01-01"),
    2023: ("2023-01-01", "2024-01-01"),
}


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
    return df[~df.index.duplicated(keep="last")].sort_index()


def _fill(df1, scan, direction, entry):
    """Возвращает fill_ts (первое касание entry в окне [scan, +10 мин]) или None."""
    t0 = pd.Timestamp(scan)
    window = df1[(df1.index >= t0) & (df1.index < t0 + pd.Timedelta(minutes=10))]
    for ts, bar in window.iterrows():
        hit = float(bar.low) <= entry if direction == "LONG" else float(bar.high) >= entry
        if hit:
            return ts
    return None


def _base_outcome(df1, fill_ts, direction, entry, stop, tp):
    """Полный исход от fill_ts (как live_filt: SL/TP до 12ч, иначе по close)."""
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


def _r_at_close(close, direction, entry, stop, sp):
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    gross = ((close - entry) if direction == "LONG" else (entry - close)) / risk
    return float(gross) - MAKER / sp - TAKER / sp


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
    pos = None  # активная позиция: dict
    htf = int(bot.CONFIG["tf7"]["htf_ratio"])
    t_since = pd.Timestamp(since)
    t_until = pd.Timestamp(until)
    rows = []
    n = len(df5)
    t0 = time.time()
    for i in range(WIN, n):
        scan_ts = pd.Timestamp(df5.index[i])
        if scan_ts < t_since:
            continue
        if scan_ts >= t_until:
            break
        if i % 8000 == 0:
            print(f"  {sym} {scan_ts.date()} rows={len(rows)} sec={time.time()-t0:.0f}", flush=True)
        sl = df5.iloc[i - (WIN - 1) : i + 1]
        sigs = bot.detect_signals(
            sl, set(), htf_ratio=htf, tf_name="tf7",
            df_confirm=None, min_sweep_atr=0.0,
        ) or []
        sigs.sort(key=lambda s: str(s.get("timestamp") or ""), reverse=True)
        scan_s = str(scan_ts)[:19]
        keys_now = set()
        for s in sigs:
            keys_now.add((str(s.get("confirm_bar_time") or "")[:19], str(s.get("direction") or "")))

        # --- трекинг смерти текущей позиции ---
        if pos is not None and not pos["closed"]:
            bar = df5.iloc[i]
            alive = (pos["cbt"], pos["dir"]) in keys_now
            if alive:
                pos["dead_cnt"] = 0
            else:
                pos["dead_cnt"] += 1
                for N in (1, 2, 3):
                    if pos["dead_cnt"] >= N and f"r_d{N}" not in pos:
                        pos[f"r_d{N}"] = _r_at_close(float(bar["close"]), pos["dir"], pos["entry"], pos["stop"], pos["sp"])
                        pos[f"ts_d{N}"] = scan_s
            if scan_ts >= pos["base_exit"]:
                pos["closed"] = True
                rows.append({
                    "sym": sym, "direction": pos["dir"], "cbt": pos["cbt"],
                    "scan": pos["scan"], "entry": pos["entry"], "stop": pos["stop"], "tp": pos["tp"],
                    "sp": pos["sp"], "fill_ts": str(pos["fill_ts"]),
                    "outcome": pos["kind"], "r": pos["base_r"],
                    "exit_ts": str(pos["base_exit"]),
                    "r_d1": pos.get("r_d1"), "ts_d1": pos.get("ts_d1"),
                    "r_d2": pos.get("r_d2"), "ts_d2": pos.get("ts_d2"),
                    "r_d3": pos.get("r_d3"), "ts_d3": pos.get("ts_d3"),
                    "dead_bars_total": pos["dead_cnt"],
                })

        # --- приём новых сигналов (как база live_filt) ---
        for s in sigs:
            h = str(s.get("hash") or "")
            if not h:
                continue
            if h in seen:
                continue
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
            if busy_until is not None and scan_ts < busy_until:
                seen.add(h)
                continue
            htf_s = str(s.get("htf_time") or "")[:19]
            ok_sw, _why = bot._sweep_valid_for_setup(
                sl, htf, htf_s,
                str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or ""),
                float(s.get("htf_sweep_level") or s.get("sweep_level") or 0),
                direction,
            )
            if not ok_sw:
                seen.add(h)
                continue
            since_tp = str(s.get("confirm_bar_time") or s.get("trigger_bar_time") or "")
            if _tp_touched(sl, direction, tp, since_tp):
                if htf_s:
                    htf_taken.add(htf_s)
                seen.add(h)
                continue
            if htf_s and htf_s in htf_taken:
                seen.add(h)
                continue
            seen.add(h)
            fill_ts = _fill(df1, scan_s, direction, entry)
            if fill_ts is None:
                continue
            got = _base_outcome(df1, fill_ts, direction, entry, stop, tp)
            if got is None:
                continue
            kind, r, exit_ts = got
            if htf_s:
                htf_taken.add(htf_s)
            busy_until = pd.Timestamp(exit_ts)
            cbt = str(s.get("confirm_bar_time") or "")[:19]
            pos = {
                "cbt": cbt, "dir": direction, "entry": entry, "stop": stop, "tp": tp,
                "sp": abs(entry - stop) / entry, "scan": scan_s, "fill_ts": fill_ts,
                "kind": kind, "base_r": r, "base_exit": pd.Timestamp(exit_ts),
                "dead_cnt": 0, "closed": False,
            }
    # хвост: если позиция не закрыта в конце
    if pos is not None and not pos["closed"]:
        rows.append({
            "sym": sym, "direction": pos["dir"], "cbt": pos["cbt"],
            "scan": pos["scan"], "entry": pos["entry"], "stop": pos["stop"], "tp": pos["tp"],
            "sp": pos["sp"], "fill_ts": str(pos["fill_ts"]),
            "outcome": pos["kind"], "r": pos["base_r"], "exit_ts": str(pos["base_exit"]),
            "r_d1": pos.get("r_d1"), "ts_d1": pos.get("ts_d1"),
            "r_d2": pos.get("r_d2"), "ts_d2": pos.get("ts_d2"),
            "r_d3": pos.get("r_d3"), "ts_d3": pos.get("ts_d3"),
            "dead_bars_total": pos["dead_cnt"],
        })
    return rows


def run_symbol(sym: str) -> str:
    sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
    logging.disable(logging.CRITICAL)
    import cisdbot as bot

    bot.CONFIG["tf7"]["detect_filters"] = {
        "atr_enabled": False,
        "vol_enabled": False,
        "d_enabled": True,
    }
    os.makedirs(OUT, exist_ok=True)
    msgs = []
    for year, (since, until) in YEARS.items():
        dst = os.path.join(OUT, f"{sym}_{year}.pkl")
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
        msgs.append(f"OK {sym} {year} rows={len(rows)} sec={time.time()-t0:.0f}")
        print(msgs[-1], flush=True)
    return " | ".join(msgs)


def main():
    os.makedirs(OUT, exist_ok=True)
    syms = sys.argv[1:] or list(PATHS)
    with Pool(min(6, len(syms))) as pool:
        for msg in pool.imap_unordered(run_symbol, syms):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
