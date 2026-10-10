"""Честный пересчёт для 5m-семейства (tf7 = 5m→4H) на каноничном якоре (confirm 5m → cbt+5).
Вопрос пользователя: почему не 5m-основной ТФ. Параметры канона tf7: лимитка 20м (4 бара), позиция 16ч,
TP1R, комиссии Bybit, min_stop 0.25%. Сравнение с tf8 (30m→8H).
"""
import glob
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf  # noqa: E402

MAKER, TAKER = 0.00036, 0.0010
MIN_STOP = 0.0025
POS_H = 16
XS = [5, 10, 15, 20, 30, 45, 60]
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]

rows = []
for sym in PAIRS:
    for f in sorted(glob.glob(f"D:/PYTHON/CISDBOT/RUNS/filters_off_full/{sym}_tf7_*.pkl")):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        if not trades:
            continue
        year = int(str(c.get("since"))[:4])
        try:
            df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        except Exception:
            continue
        ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        hi = df1["high"].to_numpy(dtype=float)
        lo = df1["low"].to_numpy(dtype=float)
        cl = df1["close"].to_numpy(dtype=float)
        step = max(1, int(round(np.median(np.diff(ts)))))
        for t in trades:
            s = sigs.get(str(t.get("hash")))
            if not s:
                continue
            entry, stop = float(t.get("entry_px") or 0), float(t.get("stop") or 0)
            if entry <= 0 or stop <= 0:
                continue
            sp = abs(entry - stop) / entry
            if sp < MIN_STOP:
                continue
            long = t.get("direction") == "LONG"
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            from_ts = (cbt + pd.Timedelta(minutes=5)).ceil("5min")
            t0 = int(from_ts.value // 60_000_000_000)
            i0 = int(np.searchsorted(ts, t0, side="left"))
            if i0 >= len(ts):
                continue
            sl = slice(i0, min(len(ts), i0 + int(max(XS) / step) + 1))
            hit = np.where(lo[sl] <= entry)[0] if long else np.where(hi[sl] >= entry)[0]
            if len(hit) == 0:
                continue
            j = i0 + int(hit[0])
            dt = float(ts[j] - t0)
            tp1 = entry + (entry - stop) if long else entry - (stop - entry)
            ks = slice(j, min(len(ts), j + int(POS_H * 60 / step) + 1))
            kl, kh = lo[ks], hi[ks]
            tp_hit = np.where(kh >= tp1)[0] if long else np.where(kl <= tp1)[0]
            sl_hit = np.where(kl <= stop)[0] if long else np.where(kh >= stop)[0]
            i_tp = int(tp_hit[0]) if len(tp_hit) else 10 ** 9
            i_sl = int(sl_hit[0]) if len(sl_hit) else 10 ** 9
            if i_tp <= i_sl and i_tp != 10 ** 9:
                out, r = "tp", 1.0 - 2 * MAKER / sp
            elif i_sl != 10 ** 9:
                out, r = "sl", -1.0 - MAKER / sp - TAKER / sp
            else:
                px = float(cl[ks][-1])
                out = "time"
                r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - MAKER / sp - TAKER / sp
            for x in XS:
                if dt <= x:
                    rows.append({"sym": sym, "year": year, "x": x, "out": out, "r": r,
                                 "dir": t.get("direction"), "sp": sp})

df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_honest.pkl")
print("tf7 (5m→4H) на каноничном якоре")
print(f"{'окно':>6} | {'сделок':>6} | {'TP':>5} {'SL':>5} {'TIME':>5} | {'WR':>6} | {'ΣR':>9} | {'avg':>7} | ср.стоп")
for x in XS:
    d = df[df.x == x]
    if d.empty:
        continue
    tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum())
    wr = 100 * tp / max(1, tp + sl)
    print(f"{x:5d}м | {len(d):6d} | {tp:5d} {sl:5d} {int((d.out=='time').sum()):5d} | {wr:5.1f}% | "
          f"{d.r.sum():+9.1f} | {d.r.mean():+.3f} | {100*d.sp.mean():.3f}%")
print()
print("--- по годам (окно 20м) ---")
d20 = df[df.x == 20]
for y in sorted(d20.year.unique()):
    dy = d20[d20.year == y]
    print(f"  {y}: n={len(dy):6d} WR={100*(dy.out=='tp').sum()/max(1,(dy.out.isin(['tp','sl'])).sum()):5.1f}% "
          f"ΣR={dy.r.sum():+8.1f} avg={dy.r.mean():+.3f}")
print()
print("--- ноги (окно 20м) ---")
for dd in ("LONG", "SHORT"):
    dz = d20[d20["dir"] == dd]
    print(f"  {dd:5s}: n={len(dz):6d} WR={100*(dz.out=='tp').sum()/max(1,(dz.out.isin(['tp','sl'])).sum()):5.1f}% "
          f"ΣR={dz.r.sum():+8.1f} avg={dz.r.mean():+.3f} | ср.стоп {100*dz.sp.mean():.3f}%")
