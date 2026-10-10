"""Лестница гранулярности подтверждения: 5/10/15/20/25/30 мин внутри 30m-окна.

Для каждого сетапа (структура из сигналов aligned-кэшей) и каждой гранулярности G:
  находим ПЕРВУЮ точку cbt+G, cbt+2G, ... внутри 30m-окна, где цена закрылась за уровнем CISD,
  вход — на следующем баре той же гранулярности (окно ожидания G минут, лимитка на уровне).
Всё честно: решение принимается только по закрытой цене на момент входа.
Исходы: TP1R / SL / таймаут 6ч, комиссии Bybit, min_stop 0.25%.
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
MIN_STOP, POS_H = 0.0025, 6
GRANS = [5, 10, 15, 20, 25, 30]
OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/REPORT_GRAN_LADDER.md"
rows = []


def sim(entry, stop, long, t0, win, ts, hi, lo, cl, step):
    sp = abs(entry - stop) / entry
    i0 = int(np.searchsorted(ts, t0, side="left"))
    if i0 >= len(ts):
        return None
    seg = slice(i0, min(len(ts), i0 + int(win / step) + 1))
    hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
    if len(hit) == 0:
        return {"out": "nofill", "r": 0.0, "t_in": None, "t_out": None}
    j = i0 + int(hit[0])
    tp1 = entry + (entry - stop) if long else entry - (stop - entry)
    ks = slice(j, min(len(ts), j + int(POS_H * 60 / step) + 1))
    kl, kh = lo[ks], hi[ks]
    tp_hit = np.where(kh >= tp1)[0] if long else np.where(kl <= tp1)[0]
    sl_hit = np.where(kl <= stop)[0] if long else np.where(kh >= stop)[0]
    i_tp = int(tp_hit[0]) if len(tp_hit) else 10 ** 9
    i_sl = int(sl_hit[0]) if len(sl_hit) else 10 ** 9
    if i_tp <= i_sl and i_tp != 10 ** 9:
        out, r, ix = "tp", 1.0 - 2 * MAKER / sp, i_tp
    elif i_sl != 10 ** 9:
        out, r, ix = "sl", -1.0 - (MAKER + TAKER) / sp, i_sl
    else:
        px = float(cl[ks][-1])
        out, ix = "time", int(cl[ks].size) - 1
        r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - (MAKER + TAKER) / sp
    xe = min(j + ix, len(ts) - 1)
    return {"out": out, "r": r, "t_in": ts[j], "t_out": ts[xe]}


for f in sorted(glob.glob("D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned/*_tf8_*.pkl")):
    p = pickle.load(open(f, "rb"))
    sym = str(p.get("symbol") or "")
    year = int(str(p.get("since"))[:4])
    sigs = {str(s.get("hash")): s for s in p.get("signals") or []}
    trades = [t for t in p.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    if not trades:
        continue
    try:
        df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
    except Exception:
        continue
    ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
    hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    step = max(1, int(round(np.median(np.diff(ts)))))
    for t in trades:
        s = sigs.get(str(t.get("hash")))
        if not s:
            continue
        entry, stop = float(s.get("entry") or 0), float(s.get("stop") or 0)
        lvl = float(s.get("cisd_level") or entry)
        if entry <= 0 or stop <= 0 or lvl <= 0:
            continue
        sp_pct = abs(entry - stop) / entry
        if sp_pct < MIN_STOP:
            continue
        long = s.get("direction") == "LONG"
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        base = {"sym": sym, "year": year, "dir": s.get("direction"), "lvl": lvl, "sp": sp_pct * 100}
        for G in GRANS:
            conf = None
            for k in range(1, 30 // G + 1):
                off = k * G
                t_off = int((cbt + pd.Timedelta(minutes=off)).value // 60_000_000_000)
                kk = int(np.searchsorted(ts, t_off, side="right")) - 1
                if kk < 0:
                    continue
                px = float(cl[kk])
                if (px > lvl) if long else (px < lvl):
                    conf = off
                    break
            if conf is None:
                continue
            t0 = int((cbt + pd.Timedelta(minutes=conf)).value // 60_000_000_000)
            # окно заявки: от подтверждения до конца 30m-бара + ещё 30 мин (как в живом боте)
            r = sim(entry, stop, long, t0, 60 - conf, ts, hi, lo, cl, step)
            if r is None:
                continue
            rows.append({**base, "G": G, "conf": conf, "minutes_before_30m": 30 - conf,
                         "out": r["out"], "r": r["r"], "t_in": r["t_in"], "t_out": r["t_out"]})
df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/gran_ladder.pkl")
lines = []


def w(x=""):
    print(x, flush=True)
    lines.append(x)


w("=" * 104)
w("# ЛЕСТНИЦА: подтверждение на 5/10/15/20/25/30 мин внутри 30m-окна, вход на следующем баре")
w(f"\nсетапов всего: {df.groupby('G').size().max() if len(df) else 0}")
w("\n## итог по гранулярности")
w(f"  {'G':>4s} {'сделок':>7s} {'не налил.':>9s} {'WR':>6s} {'ΣR':>9s} {'avg':>8s} {'вход раньше 30m, мин':>20s}")


def portfolio(d, max_pos=7, risk=0.01, start=100.0):
    d = d[d.out != "nofill"].dropna(subset=["t_in", "t_out"]).sort_values(["t_in", "sym"])
    ev = []
    for i, r in enumerate(d.itertuples()):
        ev.append((r.t_in, 0, i)); ev.append((r.t_out, 1, i))
    ev.sort(key=lambda e: (e[0], e[1]))
    op, bal, peak, dd = {}, start, start, 0.0
    for tsm, kind, i in ev:
        r = d.iloc[i]
        if kind == 0:
            if len(op) >= max_pos or r.sym in op:
                continue
            op[r.sym] = (bal * risk, r.r)
        elif r.sym in op:
            rk, rr = op.pop(r.sym)
            bal += rk * rr
            peak = max(peak, bal); dd = max(dd, (peak - bal) / peak * 100)
    return bal, dd


for G in GRANS:
    d = df[df.G == G]
    f = d[d.out != "nofill"]
    tp = int((f.out == "tp").sum()); sl = int((f.out == "sl").sum())
    fin, dd = portfolio(d)
    w(f"  {G:4d} {len(f):7d} {len(d)-len(f):9d} {100*tp/max(1,tp+sl):5.1f}% {f.r.sum():+9.1f} "
      f"{f.r.mean():+8.3f} {'':>6s} портфель ${fin:7.2f} (DD {dd:.0f}%)")
w("\n## по годам (ΣR)")
for G in GRANS:
    d = df[(df.G == G) & (df.out != "nofill")]
    w(f"  G={G:2d}: " + " | ".join(f"{y}:{d[d.year==y].r.sum():+7.1f}" for y in sorted(df.year.unique())))
w("\n## сколько входа реально ускоряется (доля сделок по числу минут до 30m-закрытия)")
d = df[(df.G == 5) & (df.out != "nofill")]
for m in (25, 20, 15, 10, 5, 0):
    w(f"  за {m:2d} мин и раньше до 30m-закрытия: {int((60*(d.minutes_before_30m>=m)).sum() and (d.minutes_before_30m>=m).sum()):6d} "
      f"({100*(d.minutes_before_30m>=m).mean():5.1f}%)")
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\nзаписано в", OUT)
