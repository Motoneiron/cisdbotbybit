"""Решающий тест: на какой популяции кэшей считался final_early поток (SOL 2024, SOL 2021).
Сравниваем с pkl: SOL 2024 = 171 сд, SOL 2021 = 157 сд (tf7+tf8)."""
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from cryptofish.adapters.features import daily_session_vwap

RUNS = r"D:/PYTHON/CISDBOT/RUNS"


def count_stream(sym, prof, year, path, conf_add, limit_h, dft_tf, cache=None):
    c = cache if cache is not None else pickle.load(open(path, "rb"))
    sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
    trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    dft, _ = load_ltf(tf=dft_tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    dft.index = pd.DatetimeIndex(dft.index)
    atr = compute_atr14(dft)
    vwap = daily_session_vwap(dft)
    df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    df1.index = pd.DatetimeIndex(df1.index)
    n = 0
    for t in trades:
        s = sigs.get(str(t.get("hash")))
        if not s:
            continue
        sb = s.get("scan_bar")
        i = int(sb) if sb is not None and 0 <= int(sb) < len(dft) else None
        if i is None:
            continue
        a = atr.iloc[i]
        if pd.isna(a) or a <= 0:
            continue
        vd = (float(dft.iloc[i]["close"]) - float(vwap.iloc[i])) / float(a)
        d = t["direction"]
        if d == "SHORT" and not (vd <= 0):
            continue
        if d == "LONG" and not (vd <= -3):
            continue
        entry = float(t["entry_px"])
        stop = float(t["stop"])
        sp = abs(entry - stop) / entry
        if sp < 0.0025:
            continue
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        from_ts = (cbt + pd.Timedelta(minutes=conf_add)).ceil("5min")
        win_end = from_ts + pd.Timedelta(hours=limit_h)
        seg = df1.loc[(df1.index >= from_ts) & (df1.index < win_end)]
        long_ = d == "LONG"
        if seg.empty:
            continue
        hit = (seg["low"] <= entry).any() if long_ else (seg["high"] >= entry).any()
        if hit:
            n += 1
    return n


for year, sym in (("2024", "SOL"), ("2021", "SOL")):
    print(f"\n=== {sym} {year} ===")
    variants = {
        "backup(ATR/VOL ON)": f"{RUNS}/backup_bot_aligned_before_filteroff/bot_aligned",
        "filters-off(09-11)": f"{RUNS}/2026-09-11/bot_aligned",
        "filters-off(09-12)": f"{RUNS}/2026-09-12/bot_aligned",
    }
    for vname, vdir in variants.items():
        total = 0
        parts = []
        for prof, conf_add, limit_h, dft_tf in (("tf7", 1, 20 / 60, "5m"), ("tf8", 5, 0.5, "30m")):
            path = f"{vdir}/{sym}_{prof}_{year}-01-01_{year}-12-31.pkl"
            try:
                c = pickle.load(open(path, "rb"))
            except FileNotFoundError:
                parts.append(f"{prof}: n/a")
                continue
            n = count_stream(sym, prof, year, path, conf_add, limit_h, dft_tf, cache=c)
            total += n
            parts.append(f"{prof}: {n}")
        print(f"  {vname:22s} -> {', '.join(parts)} | ИТОГО {total}")
    print(f"  pkl target: см. кросс-таб (SOL {year})")
