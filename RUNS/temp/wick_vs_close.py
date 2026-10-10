"""Кейс "фитиль 30m": вход по 5m-конфирму, но 30m-бар закрылся НЕ за уровнем CISD.

Разделяем канонические сделки tf8 на две группы:
  A) close_beyond — 30m-бар, внутри которого был конфирм, ЗАКРЫЛСЯ за уровнем (направление-верно);
  B) wick_only   — уровень только проткнут фитилём, close вернулся обратно.
Исходы считаем честно (1m, TP1R, 6ч, комиссии Bybit, min_stop 0.25%, якорь cbt+5).
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
MIN_STOP, CONF_MIN, POS_H, WIN = 0.0025, 5, 6, 30
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
rows = []
for sym in PAIRS:
    for f in sorted(glob.glob(f"D:/PYTHON/CISDBOT/RUNS/filters_off_full/{sym}_tf8_*.pkl")):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        if not trades:
            continue
        year = int(str(c.get("since"))[:4])
        try:
            df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
            d30, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        except Exception:
            continue
        d30.index = pd.DatetimeIndex(d30.index)
        idx30 = d30.index
        cl30 = d30["close"].to_numpy(dtype=float)
        ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
        step = max(1, int(round(np.median(np.diff(ts)))))
        for t in trades:
            s = sigs.get(str(t.get("hash")))
            if not s:
                continue
            entry, stop = float(t.get("entry_px") or 0), float(t.get("stop") or 0)
            cisd = float(s.get("cisd_level") or entry)
            if entry <= 0 or stop <= 0 or cisd <= 0:
                continue
            sp = abs(entry - stop) / entry
            if sp < MIN_STOP:
                continue
            long = t.get("direction") == "LONG"
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            # 30m-бар, внутри которого конфирм (label = его open)
            pos = idx30.searchsorted(cbt, side="right") - 1
            if pos < 0 or pos >= len(idx30):
                continue
            c30 = cl30[pos]
            beyond = (c30 > cisd) if long else (c30 < cisd)
            from_ts = (cbt + pd.Timedelta(minutes=CONF_MIN)).ceil("5min")
            t0 = int(from_ts.value // 60_000_000_000)
            i0 = int(np.searchsorted(ts, t0, side="left"))
            if i0 >= len(ts):
                continue
            sl_ = slice(i0, min(len(ts), i0 + int(WIN / step) + 1))
            hit = np.where(lo[sl_] <= entry)[0] if long else np.where(hi[sl_] >= entry)[0]
            if len(hit) == 0:
                continue
            j = i0 + int(hit[0])
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
                px = float(cl[ks][-1]); out = "time"
                r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - MAKER / sp - TAKER / sp
            rows.append({"sym": sym, "year": year, "dir": t.get("direction"), "grp": "close_beyond" if beyond else "wick_only",
                         "out": out, "r": r})
df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/wick_vs_close.pkl")
print("сделок:", len(df))


def st(name, d):
    if not len(d):
        print(f"  {name:32s}: —")
        return
    tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum())
    wr = 100 * tp / max(1, tp + sl)
    print(f"  {name:32s}: n={len(d):6d} ({100*len(d)/len(df):4.1f}%) TP={tp:5d} SL={sl:5d} "
          f"WR={wr:5.1f}% ΣR={d.r.sum():+9.1f} avg={d.r.mean():+.3f}")


print()
st("A) 30m закрылся ЗА уровнем", df[df.grp == "close_beyond"])
st("B) только фитиль (wick_only)", df[df.grp == "wick_only"])
print()
print("по ногам:")
for dd in ("LONG", "SHORT"):
    st(f"  {dd} close_beyond", df[(df["dir"] == dd) & (df.grp == "close_beyond")])
    st(f"  {dd} wick_only", df[(df["dir"] == dd) & (df.grp == "wick_only")])
print()
print("по годам (wick_only: n / ΣR | close_beyond: n / ΣR):")
for y in sorted(df.year.unique()):
    a = df[(df.year == y) & (df.grp == "close_beyond")]
    b = df[(df.year == y) & (df.grp == "wick_only")]
    print(f"  {y}: A n={len(a):5d} ΣR={a.r.sum():+8.1f} | B n={len(b):5d} ΣR={b.r.sum():+8.1f}")
