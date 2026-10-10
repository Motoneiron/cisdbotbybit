"""РЕШАЮЩАЯ СВЕРКА: какой якорь филла реально использовал движок?

Берём сетапы одного кэша, считаем исход по 1m на якорях cbt+5 (как в коде движка)
и cbt+30 (исполнимый, вход после закрытия 30m-бара), и сравниваем
с СОБСТВЕННЫМ полем сделки r_net (то, что насчитал движок).
Совпадающий якорь = тот, что был у движка.
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
POS_H, WIN = 6, 60
PAIR, YEAR = "BTC", 2024
f = sorted(glob.glob(f"D:/PYTHON/CISDBOT/RUNS/filters_off_full/{PAIR}_tf8_{YEAR}*.pkl"))[0]
c = pickle.load(open(f, "rb"))
sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
df1, _ = load_ltf(tf="1m", since=f"{YEAR}-01-01", until=f"{YEAR}-12-31", symbol=PAIR)
ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
step = max(1, int(round(np.median(np.diff(ts)))))


def sim(entry, stop, is_long, t0, tp_target=None, win_min=WIN, pos_h=POS_H):
    sp = abs(entry - stop) / entry
    t0ms = int(pd.Timestamp(t0).value // 60_000_000_000)
    i0 = int(np.searchsorted(ts, t0ms, side="left"))
    if i0 >= len(ts):
        return None, None
    seg = slice(i0, min(len(ts), i0 + int(win_min / step) + 1))
    hit = np.where(lo[seg] <= entry)[0] if is_long else np.where(hi[seg] >= entry)[0]
    if len(hit) == 0:
        return "nofill", 0.0
    j = i0 + int(hit[0])
    tp1 = float(tp_target) if tp_target else (entry + (entry - stop) if is_long else entry - (stop - entry))
    ks = slice(j, min(len(ts), j + int(pos_h * 60 / step) + 1))
    kl, kh = lo[ks], hi[ks]
    tp_hit = np.where(kh >= tp1)[0] if is_long else np.where(kl <= tp1)[0]
    sl_hit = np.where(kl <= stop)[0] if is_long else np.where(kh >= stop)[0]
    i_tp = int(tp_hit[0]) if len(tp_hit) else 10 ** 9
    i_sl = int(sl_hit[0]) if len(sl_hit) else 10 ** 9
    if i_tp <= i_sl and i_tp != 10 ** 9:
        return "tp", (abs(tp1 - entry) / abs(entry - stop)) - 2 * MAKER / sp
    if i_sl != 10 ** 9:
        return "sl", -1.0 - (MAKER + TAKER) / sp
    px = float(cl[ks][-1])
    return "time", ((px - entry) / (entry - stop) if is_long else (entry - px) / (stop - entry)) - (MAKER + TAKER) / sp


res = {}
for anchor in (5, 30):
    same_out = same_r = n = 0
    dsum = 0.0
    for t in trades:
        s = sigs.get(str(t.get("hash")))
        if not s:
            continue
        entry, stop = float(t.get("entry_px") or 0), float(t.get("stop") or 0)
        if entry <= 0 or stop <= 0:
            continue
        is_long = t.get("direction") == "LONG"
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        t0 = (cbt + pd.Timedelta(minutes=anchor)).ceil("5min")
        out, r = sim(entry, stop, is_long, t0, tp_target=t.get("tp"))
        if out is None or out == "nofill":
            continue
        n += 1
        if out == t.get("outcome"):
            same_out += 1
        if r is not None and t.get("r_net") is not None and abs(r - float(t["r_net"])) < 0.02:
            same_r += 1
        if r is not None and t.get("r_net") is not None:
            dsum += abs(r - float(t["r_net"]))
    res[anchor] = (n, same_out, same_r, dsum / max(1, n))

print(f"{PAIR} {YEAR}: сетапов {len(trades)}, посчитано {res[5][0]}")
print(f"{'якорь':>7s} {'n':>6s} {'исход совпал':>13s} {'r совпал':>9s} {'ср.|Δr|':>9s}")
for a, (n, so, sr, d) in res.items():
    print(f"  cbt+{a:<3d} {n:6d} {100*so/max(1,n):12.1f}% {100*sr/max(1,n):8.1f}% {d:9.4f}")
print()
print("встроенный ΣR движка (по r_net):", round(sum(float(t.get("r_net") or 0) for t in trades), 1))
