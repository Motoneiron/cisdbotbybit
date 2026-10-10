"""ФИНАЛЬНЫЙ пересчёт 2024-25: суммы "как реально взялось бы" на раннем детекте.

Конфиг: vwap-фильтр + min_stop 0.25% + TP1R, честные ранние окна (1m-точность).
- tf8 (30м): окно [cbt+5м, +30м], позиция 6ч.
- tf7 (5м):  окно [ceil5(cbt+1м), +20м], позиция 16ч.  (ceil5 = первый 5м-скан)
Сравнение: old (кэш, без пересчёта) против early (реализуемое).
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
    return outcome, r, hit_ts


def process(sym, prof, out_rows):
    if prof == "tf8":
        conf_add, limit_h, pos_h, dft_tf = 5, 0.5, 6, "30m"
    else:
        conf_add, limit_h, pos_h, dft_tf = 1, 20 / 60, 16, "5m"
    all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{prof}_*.pkl"),
                       key=lambda p: p.replace("\\", "/"))
    best = {}
    for f in all_files:
        name = f.replace("\\", "/").split("/")[-1]
        m = re.match(rf"{sym}_{prof}_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
        if not m:
            continue
        best[m.group(1)] = f
    res = {"old": [], "early": []}
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
            confirm_end = cbt + pd.Timedelta(minutes=conf_add)
            from_ts = confirm_end.ceil("5min")
            long = direction == "LONG"
            win_end = from_ts + pd.Timedelta(hours=limit_h)
            out = simulate(df1, from_ts, win_end, entry, stop, long, sp, pos_h)
            if out is None:
                continue
            res["early"].append({"r": out[1], "outcome": out[0], "sym": sym, "year": year,
                                 "ts": str(out[2]), "dir": direction})
            res["old"].append({"r": float(t["r_net"] or 0), "outcome": t["outcome"]})
    for key in ("old", "early"):
        k = pd.DataFrame(res[key])
        if k.empty:
            print(f"  {sym} {prof} {key}: пусто", flush=True)
            continue
        tps = int((k.outcome == "tp").sum()); sls = int((k.outcome == "sl").sum())
        wr = 100 * tps / max(1, tps + sls)
        print(f"  {sym} {prof} {key:5}: n={len(k):4d} WR={wr:.1f}% SumR={k.r.sum():+7.1f} "
              f"AvgR={k.r.mean():+.3f} (TP={tps} SL={sls} TIME={int((k.outcome=='time').sum())})", flush=True)
        out_rows.append({"sym": sym, "prof": prof, "mode": key, "n": len(k),
                         "wr": wr, "sumr": float(k.r.sum()), "avgr": float(k.r.mean())})
    return res["early"]


if __name__ == "__main__":
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else \
        ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
    rows = []
    all_early = []
    for sym in syms:
        for prof in ("tf7", "tf8"):
            try:
                e = process(sym, prof, rows)
                all_early.extend(e)
            except Exception as ex:
                print(f"{sym} {prof}: FAILED {ex!r}", flush=True)
    print("\n=== ИТОГО early (ранний детект, vwap + min_stop 0.25 + TP1R) ===")
    df = pd.DataFrame(rows)
    for prof in ("tf7", "tf8"):
        d = df[(df.prof == prof) & (df["mode"] == "early")]
        print(f"{prof}: n={int(d.n.sum())} SumR={d.sumr.sum():+.1f}")
    d = df[df["mode"] == "early"]
    print(f"ВСЕГО: n={int(d.n.sum())} SumR={d.sumr.sum():+.1f}")
    with open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/final_early_trades.pkl", "wb") as fh:
        pickle.dump(all_early, fh)
    print("детальные сделки: final_early_trades.pkl", flush=True)
