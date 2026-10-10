"""ЧЕСТНАЯ сетка таймаутов лимитки: окно [ceil5(cbt+conf), +X минут], 1m.

Конфиг: vwap + min_stop 0.25% + TP1R + комиссии.
Для каждой сделки ищем первый тач entry в окне до MAX_X минут;
для каждого X: вход действителен, если тач случился <= X минут после постановки.
Исходы не зависят от X (позиция ведётся одинаково после входа).
"""
import glob
import pickle
import re
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from cryptofish.adapters.features import daily_session_vwap

MAKER = 0.00036
TAKER = 0.0010
MIN_STOP = 0.0025
XS = [5, 10, 15, 20, 30, 45, 60, 90, 120]


def vd_at(df, i, vwap, atr):
    if i < 0 or i >= len(df):
        return None
    if pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
        return None
    return (float(df.iloc[i]["close"]) - float(vwap.iloc[i])) / float(atr.iloc[i])


def outcome_from(df1, hit_ts, entry, stop, long, sp, pos_h):
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


def process(sym, rows):
    for prof in ("tf7", "tf8"):
        if prof == "tf8":
            conf_min, pos_h, dft_tf = 5, 6, "30m"
        else:
            conf_min, pos_h, dft_tf = 1, 16, "5m"
        all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{prof}_*.pkl"),
                           key=lambda p: p.replace("\\", "/"))
        best = {}
        for f in all_files:
            name = f.replace("\\", "/").split("/")[-1]
            m = re.match(rf"{sym}_{prof}_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
            if m:
                best[m.group(1)] = f
        stats = {x: {"n": 0, "tp": 0, "sl": 0, "time": 0, "r": 0.0} for x in XS}
        lost = 0
        for year, f in sorted(best.items()):
            c = pickle.load(open(f, "rb"))
            sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
            trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
            dft, _ = load_ltf(tf=dft_tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
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
                entry = float(t["entry_px"]); stop = float(t["stop"])
                sp = abs(entry - stop) / entry
                if sp < MIN_STOP:
                    continue
                cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
                from_ts = (cbt + pd.Timedelta(minutes=conf_min)).ceil("5min")
                win_end = from_ts + pd.Timedelta(minutes=max(XS))
                long = direction == "LONG"
                seg = df1.loc[(df1.index >= from_ts) & (df1.index < win_end)]
                hit_ts = None
                for ts, row in seg.iterrows():
                    if (row["low"] <= entry) if long else (row["high"] >= entry):
                        hit_ts = ts
                        break
                if hit_ts is None:
                    lost += 1
                    continue
                out, r = outcome_from(df1, hit_ts, entry, stop, long, sp, pos_h)
                dt_min = (hit_ts - from_ts).total_seconds() / 60
                for x in XS:
                    if dt_min <= x:
                        st = stats[x]
                        st["n"] += 1
                        st["r"] += r
                        if out == "tp":
                            st["tp"] += 1
                        elif out == "sl":
                            st["sl"] += 1
                        else:
                            st["time"] += 1
        tot = sum(v["n"] for v in stats.values() if v["n"])
        base_n = stats[XS[-1]]["n"] + lost
        print(f"=== {sym} {prof} (база: vwap+sp, {base_n} кандидатов) ===", flush=True)
        for x in XS:
            st = stats[x]
            wr = 100 * st["tp"] / max(1, st["tp"] + st["sl"])
            print(f"  окно {x:3d}м: n={st['n']:4d} потеряно={base_n - st['n']:4d} "
                  f"WR={wr:5.1f}% SumR={st['r']:+7.1f} AvgR={st['r']/max(1,st['n']):+.3f}", flush=True)
        for x in XS:
            st = stats[x]
            rows.append({"sym": sym, "prof": prof, "x": x, "n": st["n"], "r": st["r"],
                         "tp": st["tp"], "sl": st["sl"]})


if __name__ == "__main__":
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["SOL"]
    rows = []
    for sym in syms:
        try:
            process(sym, rows)
        except Exception as e:
            print(f"{sym}: FAILED {e!r}", flush=True)
    print("\n=== СВОДКА ===")
    df = pd.DataFrame(rows)
    for prof in ("tf7", "tf8"):
        d = df[df.prof == prof]
        print(f"\n{prof}:")
        for x in XS:
            dx = d[d.x == x]
            if dx.empty:
                continue
            print(f"  {x:3d}м: n={int(dx.n.sum()):5d} SumR={dx.r.sum():+8.1f}")
    if not df.empty:
        d = df[df.x == XS[-1]]
        print(f"\nВСЕГО при макс. окне: n={int(d.n.sum())} SumR={d.r.sum():+.1f}")
