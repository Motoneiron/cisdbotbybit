"""Главный открытый вопрос: «ранний вход по 5m-конфирму + инвалидация».

Читает RUNS/temp/early_entry/*.pkl (движок, confirm_timeframe=5m, честный филл после close 5m-бара).
Для каждого сигнала:
  * класс по 30m-свече, внутри которой был 5m-конфирм: close_beyond / wick_only;
  * три политики выхода (1m, TP1R, комиссии Bybit, удержание 6ч, окно входа 30м):
      A as-is        — вход на 5m-конфирме, дальше обычные TP/SL/таймаут;
      B invalidation — то же, но если 30m-свеча закрылась ОБРАТНО за уровень, выходим на её close;
      C skip_wick    — то же, что текущий живой бот: wick-класс не берём вовсе.
Пишет отчёт в RUNS/temp/REPORT_EARLY_ENTRY.md
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
MIN_STOP, POS_H, WIN = 0.0025, 6, 30
OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/REPORT_EARLY_ENTRY_OLD_FULL.md"
rows = []
for f in sorted(glob.glob("D:/PYTHON/cisdbotbybit/RUNS/temp/early_entry/*.pkl")):
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
        t_close30 = int((idx30[j30] + pd.Timedelta(minutes=30)).value // 60_000_000_000)
        from_ts = (cbt + pd.Timedelta(minutes=5)).ceil("5min")
        t0 = int(from_ts.value // 60_000_000_000)
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
            out, r, ix = "tp", 1.0 - 2 * MAKER / sp_, i_tp
        elif i_sl != 10 ** 9:
            out, r, ix = "sl", -1.0 - (MAKER + TAKER) / sp_, i_sl
        else:
            px = float(cl[ks][-1])
            out, ix = "time", int(cl[ks].size) - 1
            r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - (MAKER + TAKER) / sp_
        # B: инвалидация на close 30m-свечи, если она закрылась обратно за уровень
        r_inv, out_inv = r, out
        if not beyond:
            k30 = int(np.searchsorted(ts, t_close30, side="right")) - 1
            if k30 >= j:                       # сделка уже была открыта к моменту close 30m
                px30 = float(cl[min(k30, len(cl) - 1)])
                out_inv = "inval"
                r_inv = ((px30 - entry) / (entry - stop) if long else (entry - px30) / (stop - entry)) - (MAKER + TAKER) / sp_
        rows.append({"sym": sym, "year": year, "dir": t.get("direction"), "grp": "close_beyond" if beyond else "wick_only",
                     "out": out, "r": r, "out_inv": out_inv, "r_inv": r_inv, "sp": sp_ * 100})
df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/early_entry_rows_full.pkl")
lines = []


def w(s=""):
    print(s, flush=True)
    lines.append(s)


def st(name, d, col="r"):
    if not len(d):
        w(f"  {name:42s} —")
        return
    tp = int(((d.out if col == "r" else d.out_inv) == "tp").sum())
    sl = int(((d.out if col == "r" else d.out_inv) == "sl").sum())
    ti = int(((d.out if col == "r" else d.out_inv) == "time").sum())
    iv = int(((d.out if col == "r" else d.out_inv) == "inval").sum())
    w(f"  {name:42s} n={len(d):6d} TP={tp:5d} SL={sl:5d} TIME={ti:5d} INV={iv:5d} "
      f"WR={100*tp/max(1,tp+sl):5.1f}% ΣR={d[col].sum():+9.1f} avg={d[col].mean():+.3f}")


w("=" * 100)
w("# РАННИЙ ВХОД (5m-конфирм): классы и политика инвалидации")
w(f"\nсделок: {len(df)} | доля wick_only: {100*(df.grp=='wick_only').mean():.1f}%")
w("\n## A. как есть (обычные TP1R/SL/таймаут 6ч)")
st("все", df)
st("  close_beyond", df[df.grp == "close_beyond"])
st("  wick_only", df[df.grp == "wick_only"])
w("\n## B. с инвалидацией (выход на close 30m, если свеча закрылась обратно)")
st("все", df, "r_inv")
st("  close_beyond", df[df.grp == "close_beyond"], "r_inv")
st("  wick_only", df[df.grp == "wick_only"], "r_inv")
w("\n## C. wick-класс не берём (текущий живой бот)")
st("все (только close_beyond)", df[df.grp == "close_beyond"])
w("\n## по годам: A (как есть) | B (инвалидация) | C (skip wick) — ΣR")
for y in sorted(df.year.unique()):
    dy = df[df.year == y]
    w(f"  {y}: A={dy.r.sum():+8.1f} | B={dy.r_inv.sum():+8.1f} | C={dy[dy.grp=='close_beyond'].r.sum():+8.1f}")
w("\n## по ногам: A | B")
for dd in ("LONG", "SHORT"):
    dy = df[df["dir"] == dd]
    w(f"  {dd}: A={dy.r.sum():+8.1f} | B={dy.r_inv.sum():+8.1f}")

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\nзаписано в", OUT)
