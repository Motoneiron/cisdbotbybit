"""Симуляция РАННЕГО детекта tf8: сетап берётся на закрытии 5м конфирма (не ждём 30м).

Сравнение трёх окон fill (1m точность):
- old: от entry_bar (как было)
- honest30: от ceil30(confirm_end) — текущий честный
- early5: от confirm_end — если детектить каждые 5м
"""
import glob
import pickle
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from cryptofish.adapters.features import daily_session_vwap

MAKER = 0.00036
TAKER = 0.0010


def vd_at(df, i, vwap, atr):
    if i < 0 or i >= len(df):
        return None
    if pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
        return None
    return (float(df.iloc[i]["close"]) - float(vwap.iloc[i])) / float(atr.iloc[i])


def simulate(df1, from_ts, win_end, entry, stop, long, sp, pos_h):
    seg = df1.loc[(df1.index >= from_ts) & (df1.index < win_end)]
    hit_ts = None
    for ts, row in seg.iterrows():
        if (row["high"] >= entry) if not long else (row["low"] <= entry):
            hit_ts = ts
            break
    if hit_ts is None:
        return None
    end_ts = hit_ts + pd.Timedelta(hours=pos_h)
    seg2 = df1.loc[(df1.index >= hit_ts) & (df1.index <= end_ts)]
    tp1 = entry + (entry - stop) if long else entry - (stop - entry)
    r = None
    outcome = "time"
    for ts, row in seg2.iterrows():
        if not long:
            if row["high"] >= stop:
                outcome, r = "sl", -1.0 - MAKER / sp - TAKER / sp
                break
            if row["low"] <= tp1:
                outcome, r = "tp", 1.0 - 2 * MAKER / sp
                break
        else:
            if row["low"] <= stop:
                outcome, r = "sl", -1.0 - MAKER / sp - TAKER / sp
                break
            if row["high"] >= tp1:
                outcome, r = "tp", 1.0 - 2 * MAKER / sp
                break
    if r is None:
        px = float(seg2.iloc[-1]["close"])
        r = ((entry - px) / (entry - stop) if not long else (px - entry) / (entry - stop)) - MAKER / sp - TAKER / sp
    return outcome, r


def process(sym):
    prof, main_min, limit_h, pos_h = "tf8", 30, 30 / 60, 6
    all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{prof}_*.pkl"),
                       key=lambda p: p.replace("\\", "/"))
    best = {}
    for f in all_files:
        name = f.replace("\\", "/").split("/")[-1]
        m = re.match(rf"{sym}_{prof}_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
        if not m:
            continue
        if "2024" not in name and "2025" not in name:
            continue
        best[m.group(1)] = f
    res = {"old": [], "honest30": [], "early5": []}
    for year, f in sorted(best.items()):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        dft, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        atr = compute_atr14(dft)
        vwap = daily_session_vwap(dft)
        df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        df1.index = pd.DatetimeIndex(df1.index)
        for t in trades:
            s = sigs.get(str(t.get("hash")))
            if not s:
                continue
            sb = s.get("scan_bar")
            i = int(sb) if sb is not None and 0 <= int(sb) < len(dft) else None
            if i is None:
                continue
            vd = vd_at(dft, i, vwap, atr)
            if vd is None:
                continue
            direction = t["direction"]
            if direction == "SHORT" and not (vd <= 0):
                continue
            if direction == "LONG" and not (vd <= -3):
                continue
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            confirm_end = cbt + pd.Timedelta(minutes=5)
            entry = float(t["entry_px"]); stop = float(t["stop"])
            long = direction == "LONG"
            sp = abs(entry - stop) / entry
            # окна
            for key, from_ts in (
                ("old", None),
                ("honest30", confirm_end.floor("30min") + pd.Timedelta(minutes=30)),
                ("early5", confirm_end),
            ):
                if key == "old":
                    eb = int(t["entry_bar"])
                    if eb >= len(dft):
                        continue
                    from_ts = pd.Timestamp(dft.index[eb])
                    # old: используем исход из кэша
                    res["old"].append({"r": float(t["r_net"] or 0), "outcome": t["outcome"]})
                    continue
                win_end = from_ts + pd.Timedelta(hours=limit_h)
                out = simulate(df1, from_ts, win_end, entry, stop, long, sp, pos_h)
                if out is None:
                    continue
                res[key].append({"r": out[1], "outcome": out[0]})
    print(f"=== {sym} tf8 (vwap-поток, 2024-25) ===")
    for key in ("old", "honest30", "early5"):
        k = pd.DataFrame(res[key])
        if k.empty:
            print(f"  {key}: пусто")
            continue
        tps = (k.outcome == "tp").sum(); sls = (k.outcome == "sl").sum()
        wr = 100 * tps / max(1, tps + sls)
        print(f"  {key:8}: n={len(k)} WR={wr:.1f}% SumR={k.r.sum():+.1f} AvgR={k.r.mean():+.3f} "
              f"(TP={tps} SL={sls} TIME={(k.outcome=='time').sum()})")


for sym in sys.argv[1].split(",") if len(sys.argv) > 1 else ["SOL"]:
    try:
        process(sym)
    except Exception as e:
        print(f"{sym}: FAILED {e!r}")
