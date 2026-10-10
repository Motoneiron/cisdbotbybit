"""Честный реплей 14 живых сделок 16-18.09 ДВУМЯ определениями наклона:

  A) closed_1h  — EMA3 по закрытым 1H-барам (последний час с close_time <= вход). Строго без будущего.
  B) live_1h    — EMA3 по 1H, где текущий (ещё не закрытый) час собран из 1m ДО МИНУТЫ ВХОДА
                  (то, что бот реально видит на live: не финальный close часа, а текущая цена).

Сравниваем, какой набор сделок режет каждый вариант при пороге 0.02% и мёртвой зоне.
"""
import ccxt
import numpy as np
import pandas as pd

ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
TRADES = [
    ("ADA", "LONG", "2026-09-16 02:43:53", -0.9051), ("KAS", "LONG", "2026-09-16 07:09:13", -1.0932),
    ("BTC", "LONG", "2026-09-16 11:37:49", -0.6466), ("SOL", "SHORT", "2026-09-16 13:14:59", +0.8269),
    ("DOGE", "LONG", "2026-09-16 18:30:11", +0.8395), ("BTC", "SHORT", "2026-09-16 18:38:32", -0.8639),
    ("ETH", "SHORT", "2026-09-16 19:32:13", -0.9120), ("LTC", "SHORT", "2026-09-16 19:32:13", -1.0524),
    ("ADA", "LONG", "2026-09-16 20:01:04", +0.3954), ("BNB", "SHORT", "2026-09-17 02:37:30", -0.3749),
    ("LINK", "SHORT", "2026-09-17 04:38:47", -1.1244), ("XRP", "LONG", "2026-09-17 14:32:41", -0.5950),
    ("LINK", "SHORT", "2026-09-17 18:30:00", +0.7050), ("LTC", "SHORT", "2026-09-17 19:30:00", -1.1580),
]
TH = 0.02  # %


def slope_pair(m1: pd.DataFrame, t: pd.Timestamp):
    """(A) по закрытым часам, (B) closed + текущий час, собранный из 1m до момента t."""
    h = m1["c"].resample("1h", label="left", closed="left").last().dropna()
    closed = h[h.index + pd.Timedelta(hours=1) <= t]
    # B) закрытые часы + текущий (незакрытый) час по цене на момент t
    b = closed.copy()
    part = m1.loc[m1.index <= t, "c"]
    if len(part):
        b = pd.concat([b, pd.Series({t.floor("1h"): float(part.iloc[-1])})])
        b = b[~b.index.duplicated(keep="last")].sort_index()
    out = {}
    for name, ser in (("A", closed), ("B", b)):
        if len(ser) < 4:
            out[name] = None
            continue
        e = ser.ewm(span=3, adjust=False).mean()
        out[name] = float((e.iloc[-1] / e.iloc[-2] - 1) * 100)
    return out


print(f"порог {TH}% (|slope| < порога = мёртвая зона, торгуем)\n")
print(f"{'вход UTC':17s} {'пара':5s} {'напр':5s} {'A closed':>9s} {'A вердикт':>10s} {'B live':>9s} {'B вердикт':>10s} {'net':>8s}")
res = {k: {"skip": 0, "skip_net": 0.0, "keep": 0, "keep_net": 0.0} for k in ("A", "B")}
for sym, d, ts, net in sorted(TRADES, key=lambda z: z[2]):
    t = pd.Timestamp(ts)
    o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "1m", since=int((t - pd.Timedelta(hours=14)).timestamp() * 1000), limit=1000)
    m1 = pd.DataFrame(o, columns=["ts", "o", "h", "l", "c", "v"])
    m1["dt"] = pd.to_datetime(m1.ts, unit="ms", utc=True).dt.tz_localize(None)
    m1 = m1.set_index("dt")
    sl = slope_pair(m1, t)
    line = f"{ts:17s} {sym:5s} {d:5s}"
    for k in ("A", "B"):
        v = sl[k]
        if v is None:
            line += f" {'нет данных':>9s} {'—':>10s}"
            continue
        with_tr = (d == "LONG" and (v > 0 or abs(v) < TH)) or (d == "SHORT" and (v < 0 or abs(v) < TH))
        line += f" {v:+8.3f}% {'WITH' if with_tr else 'SKIP':>10s}"
        g = "keep" if with_tr else "skip"
        res[k][g] += 1
        res[k][g + "_net"] += net
    line += f" {net:+8.3f}"
    print(line)

print()
tot = sum(t[3] for t in TRADES)
print(f"все 14 сделок: net {tot:+.3f}")
for k, lbl in (("A", "A) закрытый 1H (строго, как в боте)"), ("B", "B) live_1h (текущий час по 1m до входа)")):
    r = res[k]
    print(f"  {lbl}:")
    print(f"     SKIP {r['skip']:2d} сделок, их net {r['skip_net']:+.3f}")
    print(f"     KEEP {r['keep']:2d} сделок, их net {r['keep_net']:+.3f}")
