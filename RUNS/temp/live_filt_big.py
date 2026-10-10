"""Большая выборка как живой бот, но свип/ATR и объём выключены.

Остальное как на сервере: детект каждый закрытый 5m, касания, стоп от 0,5%,
проверка свипа, TP уже был, один сигнал на 4H-окно, одна позиция на пару,
лимит 10 минут, выход 12 часов, комиссия Bybit.
Потом режем сохранённые сделки порогами 0,40 и 2,5.
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

OUT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_filt"
PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
}
YEARS = [
    (2023, "2023-01-01", "2024-01-01"),
    (2024, "2024-01-01", "2025-01-01"),
    (2025, "2025-01-01", "2026-01-01"),
    (2026, "2026-01-01", "2026-06-24"),
]
WIN = 300
MAKER, TAKER = 0.00036, 0.0010


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


def _feats(sig, sl):
    out = {"sw": None, "vol": None, "touches": sig.get("prior_touches"), "soft": None}
    try:
        ti = sig.get("trigger_idx")
        if ti is None:
            ts = pd.Timestamp(str(sig.get("trigger_bar_time") or sig.get("timestamp")))
            ti = sl.index.get_loc(ts)
        ti = int(ti)
        level = float(sig.get("htf_sweep_level") or sig.get("sweep_level") or 0)
        direction = str(sig.get("direction") or "")
        from backtest.sweep_atr_filter import compute_atr14, sweep_atr_ratio
        from backtest.touch_filter import is_soft_dow
        from backtest.volume_filter import volume_ratio_series

        atr = compute_atr14(sl)
        if level > 0:
            out["sw"] = float(sweep_atr_ratio(sl, ti, level, direction == "SHORT", atr14=atr))
        ratios = volume_ratio_series(sl, 20)
        if 0 <= ti < len(ratios) and pd.notna(ratios.iloc[ti]):
            out["vol"] = float(ratios.iloc[ti])
        out["soft"] = bool(is_soft_dow(sl.index[ti]))
    except Exception:
        pass
    return out


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
    for i in range(WIN, n):
        scan_ts = pd.Timestamp(df5.index[i])
        if scan_ts < t_since:
            continue
        if scan_ts >= t_until:
            break
        if i % 8000 == 0:
            print(f"  {sym} {scan_ts.date()} trades={len(rows)} sec={time.time()-t0:.0f}", flush=True)
        sl = df5.iloc[i - (WIN - 1) : i + 1]
        sigs = bot.detect_signals(
            sl, seen, htf_ratio=htf, tf_name="tf7",
            df_confirm=None, min_sweep_atr=0.0,
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
                continue
            if htf_s:
                htf_taken.add(htf_s)
            got = _outcome(df1, scan_s, direction, entry, stop, tp)
            if got is None:
                continue
            kind, r, exit_ts = got
            busy_until = pd.Timestamp(exit_ts)
            feat = _feats(s, sl)
            rows.append({
                "sym": sym,
                "direction": direction,
                "outcome": kind,
                "r": r,
                "sw": feat["sw"],
                "vol": feat["vol"],
                "touches": feat["touches"],
                "soft": feat["soft"],
                "scan": scan_s,
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
    for year, since, until in YEARS:
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
        msgs.append(f"OK {sym} {year} n={len(rows)} sec={time.time()-t0:.0f}")
        print(msgs[-1], flush=True)
    return " | ".join(msgs)


def _tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n < 3:
        return float("nan")
    s = float(x.std(ddof=1))
    if s == 0:
        return float("nan")
    return float(x.mean() / (s / np.sqrt(n)))


def _show(g, label):
    x = pd.to_numeric(g["r"], errors="coerce").dropna()
    n = len(x)
    if n == 0:
        print(f"{label:22} n=0")
        return
    tp = int((g.outcome == "tp").sum())
    sl = int((g.outcome == "sl").sum())
    print(
        f"{label:22} n={n:5} avg={x.mean():+.3f} sum={x.sum():+.0f} "
        f"t={_tstat(x):+.2f} tp={tp} sl={sl}"
    )


def bucket(row):
    sw = row.sw
    if sw is None or not np.isfinite(sw) or sw < 0.40:
        return "atr"
    if row.soft:
        return "keep"
    vol = row.vol
    if vol is None or not np.isfinite(vol) or vol > 2.5:
        return "vol"
    return "keep"


def report():
    frames = []
    for sym in PATHS:
        for year, _, _ in YEARS:
            p = os.path.join(OUT, f"{sym}_{year}.pkl")
            if not os.path.exists(p):
                print("missing", p)
                return
            rows = pickle.load(open(p, "rb"))
            for r in rows:
                r["year"] = year
            frames.extend(rows)
    df = pd.DataFrame(frames)
    df["bucket"] = df.apply(bucket, axis=1)
    print("ALL", len(df))
    for title, part in (
        ("2024-26", df[df.year >= 2024]),
        ("2023", df[df.year == 2023]),
    ):
        print("\n==", title)
        _show(part, "all, ATR+vol off")
        _show(part[part.bucket == "keep"], "kept by both")
        _show(part[part.bucket == "atr"], "cut by ATR < 0.40")
        _show(part[part.bucket == "vol"], "cut by vol > 2.5")
        cut = part[part.bucket != "keep"]
        _show(cut, "cut by either")


def main():
    os.makedirs(OUT, exist_ok=True)
    with Pool(6) as pool:
        for msg in pool.imap_unordered(run_symbol, list(PATHS)):
            print(msg, flush=True)
    report()


if __name__ == "__main__":
    main()
