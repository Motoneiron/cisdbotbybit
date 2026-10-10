"""Аналитика входа по 15m-подтверждению внутри 30m-бара.

Читает RUNS/temp/confirm15/*.pkl (движок, confirm_timeframe=15m, честный филл после close 15m-бара).
Классы:
  early15 — подтверждение в ПЕРВОЙ половине 30m-бара (:00/:30) → вход ровно на 15 мин раньше, чем у 30m-бота;
  late15  — подтверждение во ВТОРОЙ половине (:15/:45) → по таймингу совпадает с закрытием 30m;
  wick    — 30m-свеча НЕ закрылась за уровнем (сетап, которого 30m-движок не берёт вовсе).
Вход: следующая 15m-свеча после подтверждающей (окно 15 мин), лимитка на CISD, TP1R, комиссии Bybit, 6ч.
Портфель: 7 слотов, 1 поз/пара, риск 1% от баланса, реинвест.
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
MIN_STOP, POS_H, WIN = 0.0025, 6, 15
OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/REPORT_CONFIRM15.md"
rows = []
for f in sorted(glob.glob("D:/PYTHON/cisdbotbybit/RUNS/temp/confirm15/*.pkl")):
    p = pickle.load(open(f, "rb"))
    sym = p.get("symbol")
    year = int(str(p.get("since"))[:4])
    sigs = {str(s.get("hash")): s for s in p.get("signals") or []}
    trades = [t for t in p.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    if not trades:
        continue
    try:
        df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        d30, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    except Exception:
        continue
    idx30 = pd.DatetimeIndex(d30.index)
    cl30 = d30["close"].to_numpy(dtype=float)
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
        sp_ = abs(entry - stop) / entry
        if sp_ < MIN_STOP:
            continue
        long = t.get("direction") == "LONG"
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        lvl = float(s.get("cisd_level") or entry)
        j30 = int(idx30.searchsorted(cbt, side="right")) - 1
        if j30 < 0 or j30 >= len(idx30):
            continue
        c30 = float(cl30[j30])
        beyond = (c30 > lvl) if long else (c30 < lvl)
        early = cbt.minute in (0, 30)
        cls = ("early15" if early else "late15") + ("" if beyond else "_wick")
        from_ts = (cbt + pd.Timedelta(minutes=15)).ceil("5min")
        t0 = int(from_ts.value // 60_000_000_000)
        i0 = int(np.searchsorted(ts, t0, side="left"))
        if i0 >= len(ts):
            continue
        seg = slice(i0, min(len(ts), i0 + int(WIN / step) + 1))
        hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
        if len(hit) == 0:
            rows.append({"sym": sym, "year": year, "dir": t.get("direction"), "cls": cls,
                         "out": "nofill", "r": 0.0, "sp": sp_ * 100,
                         "t_in": None, "t_out": None})
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
            out, r, ix = "tp", 1.0 - 2 * MAKER / sp_, i_tp
        elif i_sl != 10 ** 9:
            out, r, ix = "sl", -1.0 - (MAKER + TAKER) / sp_, i_sl
        else:
            px = float(cl[ks][-1])
            out, ix = "time", int(cl[ks].size) - 1
            r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - (MAKER + TAKER) / sp_
        rows.append({"sym": sym, "year": year, "dir": t.get("direction"), "cls": cls, "out": out, "r": r, "sp": sp_ * 100,
                     "t_in": pd.to_datetime(from_ts + pd.Timedelta(minutes=float(ts[j] - t0) % 1440)),
                     "t_out": pd.to_datetime(from_ts + pd.Timedelta(minutes=float(ts[min(j + ix, len(ts) - 1)] - t0) % 1440))})
df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/confirm15_rows.pkl")
lines = []


def w(x=""):
    print(x, flush=True)
    lines.append(x)


def st(name, d, base):
    f = d[d.out != "nofill"]
    if not len(f):
        w(f"  {name:34s} —")
        return
    tp = int((f.out == "tp").sum()); sl = int((f.out == "sl").sum()); ti = int((f.out == "time").sum())
    w(f"  {name:34s} n={len(f):6d} ({100*len(f)/max(1,len(base)):5.1f}%) TP={tp:5d} SL={sl:5d} TIME={ti:5d} "
      f"WR={100*tp/max(1,tp+sl):5.1f}% ΣR={f.r.sum():+8.1f} avg={f.r.mean():+.3f}")


w("=" * 100)
w("# 15m-ПОДТВЕРЖДЕНИЕ ВНУТРИ 30m: вход на следующем 15m-баре")
f_all = df[df.out != "nofill"]
w(f"\nвсего строк {len(df)} | налилось {len(f_all)} | не налилось {len(df)-len(f_all)}")
w("\n## по классам (A: вход 15 мин раньше / B: как 30m-бот / C: 30m-свеча не закрылась за уровнем)")
for c in ("early15", "late15", "early15_wick", "late15_wick"):
    st(c, df[df.cls == c], f_all)
w("\n## агрегаты")
st("early (все)", df[df.cls.str.startswith("early15")], f_all)
st("late (все)", df[df.cls.str.startswith("late15")], f_all)
st("только 30m-подтверждённые", df[df.cls.isin(["early15", "late15"])], f_all)
w("\n## по годам (ΣR): early | late | wick")
for y in sorted(df.year.unique()):
    dy = df[(df.year == y) & (df.out != "nofill")]
    w(f"  {y}: early={dy[dy.cls=='early15'].r.sum():+8.1f} | late={dy[dy.cls=='late15'].r.sum():+8.1f} | "
      f"wick={dy[dy.cls.str.endswith('_wick')].r.sum():+8.1f}")
w("\n## LONG/SHORT")
for dd in ("LONG", "SHORT"):
    d = df[(df["dir"] == dd) & (df.out != "nofill")]
    w(f"  {dd}: early={d[d.cls=='early15'].r.sum():+8.1f} | late={d[d.cls=='late15'].r.sum():+8.1f}")


def portfolio(d, max_pos=7, risk=0.01, start=100.0):
    d = d[d.out != "nofill"].dropna(subset=["t_in", "t_out"]).sort_values(["t_in", "sym"])
    ev = []
    for i, r in enumerate(d.itertuples()):
        ev.append((r.t_in, 0, i)); ev.append((r.t_out, 1, i))
    ev.sort(key=lambda e: (e[0], e[1]))
    op, bal, peak, dd = {}, start, start, 0.0
    for ts, kind, i in ev:
        r = d.iloc[i]
        if kind == 0:
            if len(op) >= max_pos or r.sym in op:
                continue
            op[r.sym] = (bal * risk, r.r)
        elif r.sym in op:
            rk, rr = op.pop(r.sym)
            bal += rk * rr
            peak = max(peak, bal); dd = max(dd, (peak - bal) / peak * 100)
    return bal, dd, len(op)


w("\n## портфель (7 слотов, 1%/пара, реинвест)")
for name, d in (("все 15m-сделки", df), ("только 30m-подтверждённые", df[df.cls.isin(["early15", "late15"])]),
                ("только early15", df[df.cls == "early15"])):
    fin, dd, _ = portfolio(d)
    w(f"  {name:34s} финал ${fin:8.2f} | maxDD {dd:.1f}%")

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\nзаписано в", OUT)
