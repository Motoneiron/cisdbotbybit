"""15m-подтверждение внутри 30m-бара: честная эмуляция без движка.

Для каждого сетапа (структура берется из сигналов aligned-кэшей: уровень CISD, стоп, направление):
  1) ищем первый 15m-бар ВНУТРИ 30m-окна сетапа, который ЗАКРЫЛСЯ за уровнем CISD
     (для LONG close > level, для SHORT close < level);
  2) вход — на СЛЕДУЮЩЕМ 15m-баре после подтверждающего (окно ожидания 15 мин, лимитка на уровне);
  3) сравнение с текущим ботом: тот же сетап, но вход после ЗАКРЫТИЯ 30m-бара.
Классы: confirm15 в первой половине окна (ровно на 15 мин раньше) / во второй (= как 30m-бот).
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
OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/REPORT_CONFIRM15.md"
rows = []


def sim(entry, stop, long, t0_min, win_min, ts, hi, lo, cl, step):
    tp1 = entry + (entry - stop) if long else entry - (stop - entry)
    sp = abs(entry - stop) / entry
    i0 = int(np.searchsorted(ts, t0_min, side="left"))
    if i0 >= len(ts):
        return None
    seg = slice(i0, min(len(ts), i0 + int(win_min / step) + 1))
    hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
    if len(hit) == 0:
        return {"out": "nofill", "r": 0.0, "t_in": None, "t_out": None}
    j = i0 + int(hit[0])
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
        # 15-минутные точки внутри 30m-окна: cbt+15 (первая половина) и cbt+30 (= закрытие 30m)
        conf15 = None
        for off_min in (15, 30):
            ts_off = int((cbt + pd.Timedelta(minutes=off_min)).value // 60_000_000_000)
            k = int(np.searchsorted(ts, ts_off, side="right")) - 1  # закрытие 15m-бара
            if k < 0:
                continue
            px = float(cl[k])
            if (px > lvl) if long else (px < lvl):
                conf15 = off_min
                break
        if conf15 is None:
            continue
        t0_conf = int((cbt + pd.Timedelta(minutes=conf15)).value // 60_000_000_000)
        t0_bot = int((cbt + pd.Timedelta(minutes=30)).value // 60_000_000_000)
        r15 = sim(entry, stop, long, t0_conf, 15, ts, hi, lo, cl, step)
        rb = sim(entry, stop, long, t0_bot, 30, ts, hi, lo, cl, step)
        if r15 is None or rb is None:
            continue
        rows.append({"sym": sym, "year": year, "dir": s.get("direction"),
                     "cls": "early15" if conf15 == 15 else "late15",
                     "out": r15["out"], "r": r15["r"], "t_in": r15["t_in"], "t_out": r15["t_out"],
                     "out_b": rb["out"], "r_b": rb["r"], "t_in_b": rb["t_in"], "t_out_b": rb["t_out"],
                     "lvl": lvl, "sp": sp_pct * 100, "conf": conf15})
df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/confirm15_emul.pkl")
lines = []


def w(x=""):
    print(x, flush=True)
    lines.append(x)


def st(name, d, base, col="r", oc="out"):
    f = d[d[oc] != "nofill"]
    if not len(f):
        w(f"  {name:32s} —")
        return
    tp = int((f[oc] == "tp").sum()); sl = int((f[oc] == "sl").sum()); ti = int((f[oc] == "time").sum())
    w(f"  {name:32s} n={len(f):6d} ({100*len(f)/max(1,len(base)):5.1f}%) TP={tp:5d} SL={sl:5d} TIME={ti:5d} "
      f"WR={100*tp/max(1,tp+sl):5.1f}% ΣR={f[col].sum():+8.1f} avg={f[col].mean():+.3f}")


w("=" * 100)
w("# 15m-ПОДТВЕРЖДЕНИЕ ВНУТРИ 30m: вход на следующем 15m-баре")
w(f"\nсетапов: {len(df)} | подтверждение в первой половине (early15): {int((df.cls=='early15').sum())} "
  f"({100*(df.cls=='early15').mean():.1f}%) | во второй (=как 30m-бот): {int((df.cls=='late15').sum())}")
w("\n## A. вход по 15m-подтверждению (на следующем 15m-баре)")
st("все", df, df, "r", "out")
st("  early15 (на 15 мин раньше)", df[df.cls == "early15"], df, "r", "out")
st("  late15 (как 30m-бот по времени)", df[df.cls == "late15"], df, "r", "out")
w("\n## B. для сравнения — тот же сетап, вход после закрытия 30m (текущий бот)")
st("все", df, df, "r_b", "out_b")
st("  early15-подмножество", df[df.cls == "early15"], df, "r_b", "out_b")
w("\n## по годам: A (15m) | B (30m)")
for y in sorted(df.year.unique()):
    dy = df[(df.year == y)]
    w(f"  {y}: A={dy.r.sum():+8.1f} | B={dy.r_b.sum():+8.1f}")
w("\n## по ногам: A | B")
for dd in ("LONG", "SHORT"):
    d = df[df["dir"] == dd]
    w(f"  {dd}: A={d.r.sum():+8.1f} | B={d.r_b.sum():+8.1f}")


def portfolio(d, ci, co, ri, max_pos=7, risk=0.01, start=100.0):
    d = d[d[ri].notna() if False else (d["out"] != "nofill")]
    d = d.dropna(subset=[ci, co]).sort_values([ci, "sym"])
    ev = []
    for i, r in enumerate(d.itertuples()):
        ev.append((getattr(r, ci), 0, i)); ev.append((getattr(r, co), 1, i))
    ev.sort(key=lambda e: (e[0], e[1]))
    op, bal, peak, dd = {}, start, start, 0.0
    for tsm, kind, i in ev:
        r = d.iloc[i]
        if kind == 0:
            if len(op) >= max_pos or r.sym in op:
                continue
            op[r.sym] = (bal * risk, getattr(r, "r") if ci == "t_in" else getattr(r, "r_b"))
        elif r.sym in op:
            rk, rr = op.pop(r.sym)
            bal += rk * rr
            peak = max(peak, bal); dd = max(dd, (peak - bal) / peak * 100)
    return bal, dd


w("\n## портфель (7 слотов, 1%/пара, реинвест)")
a1, a2 = portfolio(df, "t_in", "t_out", "r")
b1, b2 = portfolio(df, "t_in_b", "t_out_b", "r_b")
w(f"  A 15m-подтверждение: ${a1:8.2f} (maxDD {a2:.1f}%)")
w(f"  B вход после 30m  : ${b1:8.2f} (maxDD {b2:.1f}%)")
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\nзаписано в", OUT)
