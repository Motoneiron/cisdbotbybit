"""Валидация отсечённых гейтом сигналов за 15.09.2026 (Bybit 1m, честное окно).

Для каждого LONG/SHORT из signal_skipped (vwap-фильтр) сегодня:
  окно лимитки: [signal_time, +limit_h]  (tf7 20м, tf8 30м)
  fill: LONG — low <= entry; SHORT — high >= entry
  затем окно позиции (tf7 16ч, tf8 6ч): первое касание TP/SL по 1m.
R_net с комиссиями Bybit: TP = 1 - 2*maker/sp; SL = -1 - (maker+taker)/sp;
TIME = (close - entry)/(entry - stop) - (maker+taker)/sp  (в сторону сделки).
"""
import json
import re
import sys
import time

import numpy as np
import pandas as pd

try:
    import ccxt
except ImportError:
    print("NO CCXT"); sys.exit(1)

MAKER, TAKER = 0.00036, 0.0010
LIM = {"tf7": 20, "tf8": 30}
POSH = {"tf7": 16, "tf8": 6}
j = r"D:/PYTHON/cisdbotbybit/RUNS/temp/trades_2026-09.jsonl"
ev = [json.loads(l) for l in open(j, encoding="utf-8") if l.strip()]
sk = [e for e in ev if e.get("event") == "signal_skipped"
      and "vwap" in str(e.get("skip_reason", ""))
      and str(e.get("logged_at", "")).startswith("2026-09-15")]
print(f"отсечённых vwap-сигналов за 15.09: {len(sk)}")
rows = []
ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "linear"}})
cache = {}


def klines(sym, t0, t1):
    key = (sym, t0, t1)
    if key in cache:
        return cache[key]
    out = []
    since = int(t0.timestamp() * 1000)
    while True:
        try:
            k = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "1m", since=since, limit=1000)
        except Exception as e:
            print("  fetch err", sym, e, flush=True); time.sleep(3); continue
        if not k:
            break
        out += k
        if k[-1][0] >= int(t1.timestamp() * 1000) or len(k) < 1000:
            break
        since = k[-1][0] + 60_000
        time.sleep(0.15)
    df = pd.DataFrame(out, columns=["ts", "o", "h", "l", "c", "v"])
    df["ts"] = pd.to_datetime(df.ts, unit="ms")
    df = df.set_index("ts")
    cache[key] = df
    return df


for e in sk:
    m2 = re.search(r"Инструмент:\s*([A-Z]+)/USDT", str(e.get("skip_reason", "")))
    if not m2:
        continue
    sym = m2.group(1)
    tf = e["tf"]
    t0 = pd.Timestamp(e["logged_at"]).tz_localize(None) - pd.Timedelta(minutes=5)
    entry = float(e["signal_entry"] or e["cisd_level"])
    stop = float(e["stop"])
    tp = float(e["tp"])
    long = e["direction"] == "LONG"
    sp = abs(entry - stop) / entry
    t_end = t0 + pd.Timedelta(hours=POSH[tf])
    d = klines(sym, t0 - pd.Timedelta(minutes=2), t_end)
    if len(d) == 0:
        continue
    lim_end = t0 + pd.Timedelta(minutes=LIM[tf])
    seg = d.loc[(d.index >= t0) & (d.index <= lim_end)]
    filled = False
    hit_ts = None
    if len(seg):
        m = (seg["l"].to_numpy(float) <= entry) if long else (seg["h"].to_numpy(float) >= entry)
        if m.any():
            filled = True
            hit_ts = seg.index[int(m.argmax())]
    if not filled:
        rows.append({"sym": sym, "tf": tf, "dir": e["direction"], "sp_pct": round(100*sp, 3),
                     "res": "not_filled", "r": 0.0, "vd": (re.search(r"vd=([-+]?[0-9.]+)", str(e.get("skip_reason",""))).group(1) if re.search(r"vd=([-+]?[0-9.]+)", str(e.get("skip_reason",""))) else None)})
        continue
    seg2 = d.loc[(d.index >= hit_ts) & (d.index <= hit_ts + pd.Timedelta(hours=POSH[tf]))]
    r, res = None, "time"
    for ts_x, row in seg2.iterrows():
        if long:
            if row["l"] <= stop:
                r, res = -1.0 - MAKER/sp - TAKER/sp, "sl"; break
            if row["h"] >= tp:
                r, res = 1.0 - 2*MAKER/sp, "tp"; break
        else:
            if row["h"] >= stop:
                r, res = -1.0 - MAKER/sp - TAKER/sp, "sl"; break
            if row["l"] <= tp:
                r, res = 1.0 - 2*MAKER/sp, "tp"; break
    if r is None:
        px = float(seg2["c"].iloc[-1])
        r = ((px - entry) if long else (entry - px)) / (entry - stop) - MAKER/sp - TAKER/sp
    rows.append({"sym": sym, "tf": tf, "dir": e["direction"], "sp_pct": round(100*sp, 3),
                 "res": res, "r": round(r, 3), "vd": (re.search(r"vd=([-+]?[0-9.]+)", str(e.get("skip_reason",""))).group(1) if re.search(r"vd=([-+]?[0-9.]+)", str(e.get("skip_reason",""))) else None)})

out = pd.DataFrame(rows)
out.to_csv(r"D:/PYTHON/cisdbotbybit/RUNS/temp/_skipped_0915.csv", index=False)
print(out.to_string(index=False))
print()
for d in ("LONG", "SHORT"):
    g = out[out["dir"] == d]
    g2 = g[g.res != "not_filled"]
    print(f"{d}: сигналов {len(g)} | заполнилось {len(g2)} | ΣR {g2.r.sum():+.2f} | "
          f"TP/SL/TIME {int((g2.res=='tp').sum())}/{int((g2.res=='sl').sum())}/{int((g2.res=='time').sum())}")
print("\nЕсли бы взяли ВСЕ отсечённые сегодня: ΣR = %+.2f" % out[out.res != "not_filled"].r.sum())
