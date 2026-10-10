"""Точный пересчёт: честное окно fill по 1m данным.

Честное окно: от конца бара создания (created_bar) до +limit_h. Вход — первое касание в 1m.
Исход — по 1m барам от входа до entry+pos_h.
"""
import glob
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

MAKER = 0.00036
TAKER = 0.0010


def run(name, pattern, sym, tf_min, limit_h, pos_h):
    f = sorted(glob.glob(pattern))[-1]
    c = pickle.load(open(f, "rb"))
    df1, _ = load_ltf(tf="1m", since="2024-01-01", until="2024-12-31", symbol=sym)
    df1.index = pd.DatetimeIndex(df1.index)
    dft, _ = load_ltf(tf=f"{tf_min}m", since="2024-01-01", until="2024-12-31", symbol=sym)
    dft.index = pd.DatetimeIndex(dft.index)

    trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    n_all = len(trades)
    r_all = sum(float(t.get("r_net") or 0) for t in trades)
    tp_all = sum(1 for t in trades if t["outcome"] == "tp")
    sl_all = sum(1 for t in trades if t["outcome"] == "sl")

    kept = []
    for t in trades:
        cb = int(t["created_bar"])
        if cb >= len(dft):
            continue
        created_end = pd.Timestamp(dft.index[cb]) + pd.Timedelta(minutes=tf_min)
        win_end = created_end + pd.Timedelta(hours=limit_h)
        entry = float(t["entry_px"])
        stop = float(t["stop"])
        tp = float(t["tp"])
        long = t["direction"] == "LONG"
        sp = abs(entry - stop) / entry

        seg = df1.loc[(df1.index >= created_end) & (df1.index < win_end)]
        hit_ts = None
        for ts, row in seg.iterrows():
            if (row["high"] >= entry) if not long else (row["low"] <= entry):
                hit_ts = ts
                break
        if hit_ts is None:
            continue
        # исход: от входа до entry + pos_h
        end_ts = hit_ts + pd.Timedelta(hours=pos_h)
        seg2 = df1.loc[(df1.index >= hit_ts) & (df1.index <= end_ts)]
        outcome, r = "time", None
        for ts, row in seg2.iterrows():
            if not long:
                if row["high"] >= stop:
                    outcome, r = "sl", -1.0 - MAKER / sp - TAKER / sp
                    break
                if row["low"] <= tp:
                    outcome, r = "tp", 1.0 - MAKER / sp - MAKER / sp
                    break
            else:
                if row["low"] <= stop:
                    outcome, r = "sl", -1.0 - MAKER / sp - TAKER / sp
                    break
                if row["high"] >= tp:
                    outcome, r = "tp", 1.0 - MAKER / sp - MAKER / sp
                    break
        if r is None:
            px = float(seg2.iloc[-1]["close"])
            rr = (entry - px) / (stop - entry) if not long else (px - entry) / (entry - stop)
            r = rr - MAKER / sp - TAKER / sp
        kept.append({"outcome": outcome, "r": r})

    k = pd.DataFrame(kept)
    tps = (k.outcome == "tp").sum()
    sls = (k.outcome == "sl").sum()
    wr = 100 * tps / max(1, tps + sls)
    print(f"=== {name} ===")
    print(f"было:   n={n_all} TP={tp_all} SL={sl_all} SumR={r_all:+.1f} AvgR={r_all/max(1,n_all):+.3f}")
    print(f"честно: n={len(k)} TP={tps} SL={sls} TIME={(k.outcome=='time').sum()} "
          f"WR={wr:.1f}% SumR={k.r.sum():+.1f} AvgR={k.r.mean():+.3f}")
    print(f"потеряно: {n_all-len(k)} ({(n_all-len(k))/max(1,n_all)*100:.0f}%)")
    print()


run("SOL tf7 2024", r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf7_2024*.pkl", "SOL", 5, 20/60, 16)
run("SOL tf8 2024", r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf8_2024*.pkl", "SOL", 30, 30/60, 6)
