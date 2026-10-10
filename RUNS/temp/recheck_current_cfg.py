"""Честный пересчёт для ТЕКУЩЕГО конфига: filters-off кэши + vwap + TP1R + честное окно.

Для каждой vwap-прошедшей LIMIT-сделки:
- честное окно from = ceil_main(confirm_end), до +limit_h
- вход по первому касанию в 1m
- исход по 1m: TP1R / SL / time (6ч/16ч)
- r с комиссиями
Сравнение: как в кэше (TP1R по старому входу) vs честно.
"""
import glob
import pickle
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


def process(sym, prof, main_min, limit_h, pos_h):
    # выбрать самый свежий файл на год (как best_files: приоритет — поздняя папка)
    all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{prof}_*.pkl"),
                       key=lambda p: p.replace("\\", "/"))
    best = {}
    import re
    for f in all_files:
        name = f.replace("\\", "/").split("/")[-1]
        m = re.match(rf"{sym}_{prof}_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
        if not m:
            continue
        year = m.group(1)
        if "2024" not in name and "2025" not in name:
            continue
        folder = f.replace("\\", "/").split("/")[-2]
        best[year] = (folder, f)  # sorted → последний = свежий
    rows = []
    for year, (folder, f) in sorted(best.items()):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        if not trades:
            continue
        dft, _ = load_ltf(tf=f"{main_min}m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        atr = compute_atr14(dft)
        vwap = daily_session_vwap(dft)
        df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        df1.index = pd.DatetimeIndex(df1.index)

        for t in trades:
            s = sigs.get(str(t.get("hash")))
            if not s:
                continue
            # vwap-фильтр по scan_bar
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
            # конфирм и честное окно
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            ctf = str(s.get("confirm_timeframe") or "1m")
            cadd = 5 if ctf == "5m" else 1
            confirm_end = cbt + pd.Timedelta(minutes=cadd)
            from_ts = confirm_end.ceil(f"{main_min}min")
            win_end = from_ts + pd.Timedelta(hours=limit_h)

            entry = float(t["entry_px"])
            stop = float(t["stop"])
            long = direction == "LONG"
            risk = abs(entry - stop)
            sp = risk / entry
            tp1 = entry + risk if long else entry - risk

            # БЫЛО (как в старом кэше): r1r от entry_bar, симуляция по 1m от времени entry_bar
            # (упростим: считаем от времени entry_bar)
            eb = int(t["entry_bar"])
            if eb < len(dft):
                t0 = pd.Timestamp(dft.index[eb])
            else:
                t0 = None

            seg = df1.loc[(df1.index >= from_ts) & (df1.index < win_end)]
            hit_ts = None
            for ts, row in seg.iterrows():
                if (row["high"] >= entry) if not long else (row["low"] <= entry):
                    hit_ts = ts
                    break
            if hit_ts is None:
                rows.append({"kept": 0})
                continue
            end_ts = hit_ts + pd.Timedelta(hours=pos_h)
            seg2 = df1.loc[(df1.index >= hit_ts) & (df1.index <= end_ts)]
            outcome, r = "time", None
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
                r = ((entry - px) / risk if not long else (px - entry) / risk) - MAKER / sp - TAKER / sp
            rows.append({"kept": 1, "outcome": outcome, "r": r})

    k = pd.DataFrame(rows)
    kk = k[k.kept == 1]
    tps = (kk.outcome == "tp").sum()
    sls = (kk.outcome == "sl").sum()
    wr = 100 * tps / max(1, tps + sls)
    print(f"{sym} {prof}: vwap-всего={len(k)}, честно выжило={len(kk)} ({100*len(kk)/max(1,len(k)):.0f}%) "
          f"WR={wr:.1f}% SumR={kk.r.sum():+.1f} AvgR={kk.r.mean():+.3f}", flush=True)
    return kk


import sys as _sys
_sym_list = _sys.argv[1].split(",") if len(_sys.argv) > 1 else ["SOL"]
for _sym in _sym_list:
    for prof, mm, lh, ph in (("tf7", 5, 20 / 60, 16), ("tf8", 30, 30 / 60, 6)):
        try:
            process(_sym, prof, mm, lh, ph)
        except Exception as _e:
            print(f"{_sym} {prof}: FAILED {_e!r}", flush=True)

