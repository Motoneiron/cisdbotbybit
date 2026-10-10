"""Переоценка сделок бэктеста с 'честным' окном fill.

Честное окно: fill только с бара СЛЕДУЮЩЕГО за created_bar (когда live-бот уже выставил бы лимитку).
Для каждой LIMIT-сделки: ищем первое касание в окне (created_bar+1 .. +limit_bars).
Если нет — сделка исчезает. Если есть — пересчёт исхода по барам от входа.
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


def simulate_trade(t, df, entry_bar_new, pos_bars):
    entry = float(t["entry_px"])
    stop = float(t["stop"])
    tp = float(t["tp"])
    sp = abs(entry - stop) / entry
    long = t["direction"] == "LONG"
    last_i = min(entry_bar_new + pos_bars, len(df) - 1)
    for i in range(entry_bar_new, last_i + 1):
        row = df.iloc[i]
        if long:
            if row["low"] <= stop:
                return "sl", -1.0 - MAKER / sp - TAKER / sp, i
            if row["high"] >= tp:
                return "tp", 1.0 - MAKER / sp - MAKER / sp, i
        else:
            if row["high"] >= stop:
                return "sl", -1.0 - MAKER / sp - TAKER / sp, i
            if row["low"] <= tp:
                return "tp", 1.0 - MAKER / sp - MAKER / sp, i
    px = float(df.iloc[last_i]["close"])
    r = (px - entry) / (stop - entry) if not long else (entry - px) / (entry - stop)
    return "time", r - MAKER / sp - TAKER / sp, last_i


for pattern, name, main_min, limit_b, pos_b in [
    (r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf7_2024*.pkl", "SOL tf7 2024", 5, 4, 192),
    (r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf8_2024*.pkl", "SOL tf8 2024", 30, 1, 12),
]:
    f = sorted(glob.glob(pattern))[-1]
    c = pickle.load(open(f, "rb"))
    df, _ = load_ltf(tf=f"{main_min}m", since="2024-01-01", until="2024-12-31", symbol="SOL")
    df.index = pd.DatetimeIndex(df.index)

    trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    n_all = len(trades)
    r_all = sum(float(t.get("r_net") or 0) for t in trades)
    tp_all = sum(1 for t in trades if t["outcome"] == "tp")
    sl_all = sum(1 for t in trades if t["outcome"] == "sl")

    kept = []
    for t in trades:
        cb = int(t["created_bar"])
        entry = float(t["entry_px"])
        long = t["direction"] == "LONG"
        hit_bar = None
        for b in range(cb + 1, min(cb + 1 + limit_b, len(df))):
            row = df.iloc[b]
            if (row["high"] >= entry) if not long else (row["low"] <= entry):
                hit_bar = b
                break
        if hit_bar is None:
            continue
        out, r, xb = simulate_trade(t, df, hit_bar, pos_b)
        kept.append({"outcome": out, "r": r})

    k = pd.DataFrame(kept)
    wr = 100 * (k.outcome == "tp").sum() / max(1, (k.outcome.isin(["tp", "sl"])).sum())
    print(f"=== {name} ===")
    print(f"было:  n={n_all} TP={tp_all} SL={sl_all} SumR={r_all:+.1f} AvgR={r_all/max(1,n_all):+.3f}")
    print(f"честно: n={len(k)} SumR={k.r.sum():+.1f} AvgR={k.r.mean():+.3f} "
          f"(TP={(k.outcome=='tp').sum()} SL={(k.outcome=='sl').sum()} TIME={(k.outcome=='time').sum()})")
    print(f"потеряно сделок: {n_all - len(k)} ({(n_all - len(k))/max(1,n_all)*100:.0f}%)")
    print()
