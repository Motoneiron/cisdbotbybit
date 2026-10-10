"""Против-трендовые сделки: разделяем канонические tf8 по согласию с трендом EMA3 на 1H.
Тренд = slope = EMA3(1H)[i]/EMA3(1H)[i-1]-1 по ЗАКРЫТЫМ 1H-барам к from_ts (как в правилах бота).
Группы: WITH (LONG при slope>+0.02%, SHORT при slope<-0.02%) против AGAINST (наоборот).
Исходы: 1m, TP1R, 6ч, комиссии Bybit, min_stop 0.25%, якорь cbt+5.
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
MIN_STOP, CONF_MIN, POS_H, WIN, THR = 0.0025, 5, 6, 30, 0.0002
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
        ema3 = d30["close"].ewm(span=3, adjust=False).mean()
        h1 = ema3.resample("1h", label="left", closed="left").last().dropna()
        slope = (h1 / h1.shift(1) - 1).dropna()
        h1_min = h1.index.to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        sl_v = slope.to_numpy(dtype=float)
        ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
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
            from_ts = (cbt + pd.Timedelta(minutes=CONF_MIN)).ceil("5min")
            t0 = int(from_ts.value // 60_000_000_000)
            # последний ЗАКРЫТЫЙ 1H-бар к from_ts: его конец <= from_ts
            k = int(np.searchsorted(h1_min + 60, t0, side="right")) - 1
            if k < 2 or not np.isfinite(sl_v[k]):
                continue
            sl = sl_v[k]
            with_tr = (long and sl > THR) or ((not long) and sl < -THR)
            i0 = int(np.searchsorted(ts, t0, side="left"))
            if i0 >= len(ts):
                continue
            seg = slice(i0, min(len(ts), i0 + int(WIN / step) + 1))
            hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
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
            rows.append({"sym": sym, "year": year, "dir": t.get("direction"),
                         "grp": "WITH" if with_tr else "AGAINST", "slope": sl, "out": out, "r": r})
df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/trend_split.pkl")
print("сделок:", len(df), "| доля AGAINST: %.1f%%" % (100 * (df.grp == "AGAINST").mean()))


def st(name, d):
    if not len(d):
        print(f"  {name:24s}: —"); return
    tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum())
    print(f"  {name:24s}: n={len(d):6d} ({100*len(d)/len(df):4.1f}%) TP={tp:5d} SL={sl:5d} "
          f"WR={100*tp/max(1,tp+sl):5.1f}% ΣR={d.r.sum():+9.1f} avg={d.r.mean():+.3f}")


print()
st("WITH (по тренду EMA3 1H)", df[df.grp == "WITH"])
st("AGAINST (против тренда)", df[df.grp == "AGAINST"])
print()
for dd in ("LONG", "SHORT"):
    st(f"{dd} WITH", df[(df["dir"] == dd) & (df.grp == "WITH")])
    st(f"{dd} AGAINST", df[(df["dir"] == dd) & (df.grp == "AGAINST")])
print()
print("по годам (AGAINST n / ΣR | WITH n / ΣR):")
for y in sorted(df.year.unique()):
    a = df[(df.year == y) & (df.grp == "AGAINST")]; w = df[(df.year == y) & (df.grp == "WITH")]
    print(f"  {y}: A n={len(a):5d} ΣR={a.r.sum():+8.1f} | W n={len(w):5d} ΣR={w.r.sum():+8.1f}")
print()
print("квартили |slope| против тренда (AGAINST: сила против тренда):")
ag = df[df.grp == "AGAINST"].copy()
ag["abs_slope"] = ag.slope.abs()
for lab, q in (("слабый", ag.abs_slope.quantile(0.33)), ("средний", ag.abs_slope.quantile(0.66))):
    pass
q1, q2 = ag.abs_slope.quantile(0.33), ag.abs_slope.quantile(0.66)
st("AGAINST слабый", ag[ag.abs_slope <= q1])
st("AGAINST средний", ag[(ag.abs_slope > q1) & (ag.abs_slope <= q2)])
st("AGAINST сильный", ag[ag.abs_slope > q2])
